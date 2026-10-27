import csv,re,sys,traceback,collections,io,os,threading
import qrcode
from PIL import Image, ImageDraw, ImageFont, ImageOps
from pathlib import Path
import tkinter as tk
from tkinter import filedialog,messagebox
import pymupdf as fitz

MM=72/25.4
W,H=100*MM,150*MM

def extract_page(pg):
    t=pg.get_text()
    order=re.search(r'Order ID:\s*(\d+)',t)
    track=re.search(r'Tracking number:\s*([A-Z0-9]+)',t,re.I)
    if not order or not track: raise ValueError('Lista de embalagem sem ID do pedido ou rastreio')
    words=pg.get_text('words')
    bottom=min((w[1] for w in words if w[4]=='Qty' and w[0]>245 and w[1]>90),default=pg.rect.height)
    cells=[w for w in words if 85<=w[1]<bottom-1]
    quantities=sorted([(w[1],w[4]) for w in cells if w[0]>=250 and w[4].isdigit()])
    if not quantities: raise ValueError('Quantidade não identificada na lista de embalagem')
    items=[]
    for j,(start,qty) in enumerate(quantities):
        end=quantities[j+1][0] if j+1<len(quantities) else bottom
        # Use row position, not adjacent SKU columns, to keep multiple items separate.
        selected=[w for w in cells if start-2<=w[1]<end-1]
        def field(lo,hi):
            lines={}
            for w in selected:
                if lo<=w[0]<hi: lines.setdefault(round(w[1]/3)*3,[]).append(w)
            return ' '.join(' '.join(q[4] for q in sorted(v,key=lambda x:x[0])) for _,v in sorted(lines.items())).strip()
        name=field(0,129);variation=field(129,176);sku=field(176,250)
        if not name: raise ValueError('Nome de produto ausente na lista de embalagem')
        items.append((name,variation,sku or 'NAO CADASTRADO',int(qty)))
    return order.group(1),track.group(1),items

def split_words(text,width=53):
    words=text.split();lines=[];line=''
    for word in words:
        if len(line)+len(word)+1>width and line: lines.append(line);line=''
        line=(line+' '+word).strip()
    if line:lines.append(line)
    return lines

def normsku(s):
    return ' '.join((s or '').strip().upper().split())

def primary_sku(items,volume):
    valid=[(normsku(s),q) for _,_,s,q in items if normsku(s) not in ('','NAO CADASTRADO')]
    if not valid:return 'NAO CADASTRADO'
    return sorted(valid,key=lambda z:(-z[1],-volume[z[0]],z[0]))[0][0]

def sku_group(sku):
    """Product family is the segment before the first hyphen.

    Example: R003-PRETA-G and R003-BRANCA-G both belong to R003.
    """
    sku = normsku(sku)
    if sku in ('', 'NAO CADASTRADO'):
        return 'NAO CADASTRADO'
    return sku.split('-', 1)[0].strip()

def create(source,target,report):
    doc=fitz.open(source);out=fitz.open();rows=[];seen=set()
    if len(doc)%2: raise ValueError('PDF com numero impar de paginas: nao e seguro associar etiquetas e listas')
    packages=[];volume=collections.Counter()
    for i in range(0,len(doc),2):
        try:
            order,track,items=extract_page(doc[i+1])
            for _,_,sku,qty in items:
                s=normsku(sku)
                if s not in ('','NAO CADASTRADO'):volume[s]+=qty
            packages.append((i,order,track,items,None))
        except Exception as e:
            packages.append((i,'','',[],str(e)))
    # Total units across all variations of the same product family.
    family_volume=collections.Counter()
    for sku,qty in volume.items():
        family_volume[sku_group(sku)]+=qty
    def sort_key(p):
        sku=primary_sku(p[3],volume)
        family=sku_group(sku)
        return (bool(p[4]),family=='NAO CADASTRADO',
                -family_volume[family],family,sku,p[0])
    packages.sort(key=sort_key)
    for i,_,_,_,pre_error in packages:
        label,pack=doc[i],doc[i+1];order='';track='' 
        try:
            if pre_error:raise ValueError(pre_error)
            order,track,items=extract_page(pack)
            labeltext=label.get_text()
            if track not in re.sub(r'\s+','',labeltext): raise ValueError('Rastreio da etiqueta diferente da lista de embalagem')
            if order in seen: raise ValueError('ID de pedido duplicado no PDF')
            seen.add(order)
            # QR payload: order and all SKU/quantity pairs only.
            # Tracking remains printed and checked against the original label.
            payload='\n'.join(
                ['P:'+order] +
                ['Sku:'+sku+';Q:'+str(qty) for _,_,sku,qty in items]
            )
            qr=qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_Q,
                              box_size=12,border=4)
            qr.add_data(payload, optimize=0)
            qr.make(fit=True)
            qr_modules=len(qr.modules)+8
            qr_image=qr.make_image(fill_color='black',back_color='white').convert('RGB')
            module_px=12
            qr_pixels=qr_image.width
            cx=cy=qr_pixels//2
            # Original MM mark: blue/orange with its exact overlapping geometry.
            # Circular white reserve, large enough to show both letterforms.
            diameter=round(module_px*6.0)
            circle=Image.new('RGBA',(diameter,diameter),(255,255,255,0))
            cd=ImageDraw.Draw(circle)
            cd.ellipse((0,0,diameter-1,diameter-1),
                       fill=(255,255,255,255),outline=(0,0,0,255),
                       width=max(2,round(module_px*.18)))
            logo=Image.open(Path(__file__).resolve().parent/'logo_multiplo_mix.png').convert('RGBA')
            logo.thumbnail((round(diameter*.80),round(diameter*.53)),
                           Image.Resampling.LANCZOS)
            circle.alpha_composite(logo,((diameter-logo.width)//2,
                                         (diameter-logo.height)//2))
            qr_image.paste(circle.convert('RGB'),
                           (cx-diameter//2,cy-diameter//2),circle.getchannel('A'))
            qr_buffer=io.BytesIO()
            qr_image.save(qr_buffer,format='PNG')
            # Minimum 3.5 printer dots per module at 203 dpi; enlarge if needed.
            qr_size=max(30*MM,qr_modules*3.5*72/203)
            if qr_size>45*MM:
                raise ValueError('QR muito denso para leitura segura; pedido com muitos itens')
            qr_dots=(qr_size/72*203)/qr_modules
            # Text is wrapped to the space left of the QR; no quantity is hidden.
            left_width=W-qr_size-19
            def wrap_printed(value,size=7.0):
                words=value.split()
                result=[];current=''
                for word in words:
                    candidate=(current+' '+word).strip()
                    if current and fitz.get_text_length(candidate,fontname='hebo',fontsize=size)>left_width:
                        result.append(current);current=word
                    else:current=candidate
                    if fitz.get_text_length(current,fontname='hebo',fontsize=size)>left_width:
                        # Long unbroken SKU strings are split, not truncated.
                        while current and fitz.get_text_length(current,fontname='hebo',fontsize=size)>left_width:
                            cut=len(current)-1
                            while cut>1 and fitz.get_text_length(current[:cut],fontname='hebo',fontsize=size)>left_width:
                                cut-=1
                            result.append(current[:cut]);current=current[cut:]
                if current:result.append(current)
                return result
            footer_lines=[('TRACKING: '+track,7.5,True)]
            for name,var,sku,qty in items:
                for line in wrap_printed('SKU: '+sku,8.5):
                    footer_lines.append((line,8.5,True))
                footer_lines.append(('QTD: '+str(qty),8.5,True))
                for line in wrap_printed('PRODUTO: '+name,6.7):
                    footer_lines.append((line,6.7,False))
                for line in wrap_printed('VARIACAO: '+(var or 'PADRAO'),8.2):
                    footer_lines.append((line,8.2,True))
                footer_lines.append(('',4,False))
            text_height=sum((size+2 if line else 4) for line,size,_ in footer_lines)+12
            footer_height=max(qr_size+16,text_height)
            if footer_height>H-160:
                raise ValueError('Muitos produtos para uma etiqueta: nao sera cortado nenhum dado')
            boundary=H-footer_height
            page=out.new_page(width=W,height=H)
            # Original transport label remains intact and proportional.
            clip=fitz.Rect(18,8,278,409)
            page.show_pdf_page(fitz.Rect(5,4,W-5,boundary-5),doc,i,clip=clip,keep_proportion=True)
            page.draw_line(fitz.Point(6,boundary),fitz.Point(W-6,boundary),color=(0,0,0),width=.8)
            page.insert_image(fitz.Rect(W-qr_size-5,boundary+7,W-5,boundary+7+qr_size),
                              stream=qr_buffer.getvalue())
            y=boundary+8
            for line,size,is_bold in footer_lines:
                if not line:y+=4;continue
                y+=size+2
                page.insert_text((8,y),line,fontsize=size,fontname='hebo' if is_bold else 'helv')
            if y>H-3:
                raise ValueError('Conferencia ultrapassou o limite de 150 mm')
            if qr_dots<2:
                qr_warning='AVISO: QR denso para impressora 203 dpi; testar leitura'
            else:
                qr_warning=''
            rows.append((order,track,'GERADA','; '.join(filter(None, ['SKU NAO CADASTRADO' if any(s=='NAO CADASTRADO' for _,_,s,_ in items) else '',qr_warning]))))
        except Exception as e:
            if len(out)>sum(r[2]=='GERADA' for r in rows):out.delete_page(len(out)-1)
            rows.append((order,track,'NAO GERADA',f'Paginas {i+1}-{i+2}: {e}'))
    with open(report,'w',newline='',encoding='utf-8-sig') as f:
        wr=csv.writer(f,delimiter=';');wr.writerow(['ID do pedido','Rastreio','Status','Motivo']);wr.writerows(rows)
    errors=[r for r in rows if r[2]!='GERADA']
    if errors:
        if len(out):out.save(str(Path(target).with_name(Path(target).stem+'_PARCIAL_NAO_IMPRIMIR.pdf')),garbage=3,deflate=True)
        return len(rows)-len(errors),len(errors),False
    out.save(target,garbage=3,deflate=True)
    return len(rows),0,True

def main():
    root=tk.Tk()
    root.title('TikTok Shop | Central de Etiquetas')
    root.geometry('850x660')
    root.minsize(740,620)

    # Neutral dark palette with restrained TikTok accents.
    BG='#101419'; SURFACE='#1A2027'; FIELD='#141A21'
    BORDER='#303942'; TEXT='#F3F5F7'; MUTED='#A3AEB9'
    CYAN='#60D9D4'; PINK='#E57B9A'; SUCCESS='#83D7AF'; WARNING='#F2C47D'
    FONT='Segoe UI'
    root.configure(bg=BG)

    source=tk.StringVar()
    target=tk.StringVar()
    status=tk.StringVar(value='Aguardando arquivo')
    detail=tk.StringVar(value='Selecione o PDF original para começar.')
    last={'pdf':'','csv':''}
    busy={'value':False}

    def lbl(parent,value,size=10,color=TEXT,bold=False,bg=None):
        return tk.Label(parent,text=value,font=(FONT,size,'bold' if bold else 'normal'),
                        fg=color,bg=bg or parent.cget('bg'),anchor='w')

    shell=tk.Frame(root,bg=BG)
    shell.pack(fill='both',expand=True,padx=34,pady=(27,22))
    top=tk.Frame(shell,bg=BG)
    top.pack(fill='x')
    mark=tk.Frame(top,bg=CYAN,width=5,height=48)
    mark.pack(side='left',padx=(0,15))
    mark.pack_propagate(False)
    brand=tk.Frame(top,bg=BG)
    brand.pack(side='left',fill='x',expand=True)
    lbl(brand,'TIKTOK SHOP  /  FERRAMENTAS DO VENDEDOR',9,CYAN,True).pack(anchor='w')
    lbl(brand,'Central de etiquetas',25,TEXT,True).pack(anchor='w',pady=(3,0))
    version=tk.Label(top,text='VERSÃO 16',font=(FONT,9,'bold'),fg=MUTED,
                     bg=SURFACE,padx=12,pady=7)
    version.pack(side='right',anchor='n')

    lbl(shell,'Converta e organize suas etiquetas para conferência e expedição.',
        10,MUTED,bg=BG).pack(anchor='w',pady=(12,21))

    card=tk.Frame(shell,bg=SURFACE,highlightbackground=BORDER,highlightthickness=1)
    card.pack(fill='both',expand=True)
    inner=tk.Frame(card,bg=SURFACE)
    inner.pack(fill='both',expand=True,padx=26,pady=24)

    def field(title,number,var,action,callback):
        section=tk.Frame(inner,bg=SURFACE)
        section.pack(fill='x',pady=(0,22))
        head=tk.Frame(section,bg=SURFACE)
        head.pack(fill='x',pady=(0,10))
        lbl(head,number,9,CYAN,True).pack(side='left',padx=(0,11))
        lbl(head,title,10,TEXT,True).pack(side='left')
        line=tk.Frame(section,bg=SURFACE)
        line.pack(fill='x')
        entry=tk.Entry(line,textvariable=var,font=(FONT,10),bg=FIELD,fg=TEXT,
                       insertbackground=TEXT,selectbackground='#30545B',
                       relief='flat',highlightbackground=BORDER,highlightthickness=1)
        entry.pack(side='left',fill='x',expand=True,ipady=12)
        button=tk.Button(line,text=action,command=callback,font=(FONT,10,'bold'),
                         bg='#2A343E',fg=TEXT,activebackground='#3B4853',
                         activeforeground=TEXT,relief='flat',bd=0,
                         cursor='hand2',padx=16,pady=11)
        button.pack(side='left',padx=(11,0))
        return entry

    def pick_source():
        path=filedialog.askopenfilename(parent=root,title='Selecione o PDF original do TikTok',
                                        filetypes=[('Arquivo PDF','*.pdf')])
        if path:
            source.set(path)
            if not target.get().strip():
                target.set(str(Path(path).with_name('ETIQUETAS_TIKTOK_CONFERIDAS.pdf')))
            status.set('PDF selecionado')
            detail.set('Pronto para iniciar a conversão.')

    def pick_target():
        path=filedialog.asksaveasfilename(parent=root,title='Escolha o destino',
                                          defaultextension='.pdf',
                                          initialfile='ETIQUETAS_TIKTOK_CONFERIDAS.pdf',
                                          filetypes=[('Arquivo PDF','*.pdf')])
        if path: target.set(path)

    field('PDF ORIGINAL DO TIKTOK','01',source,'Selecionar PDF',pick_source)
    field('DESTINO DAS ETIQUETAS','02',target,'Escolher local',pick_target)

    line=tk.Frame(inner,bg=BORDER,height=1)
    line.pack(fill='x',pady=(0,20))

    statusbox=tk.Frame(inner,bg=FIELD,highlightbackground=BORDER,highlightthickness=1)
    statusbox.pack(fill='x')
    statusinner=tk.Frame(statusbox,bg=FIELD)
    statusinner.pack(fill='x',padx=17,pady=14)
    dot=tk.Label(statusinner,text='●',font=(FONT,13),fg=CYAN,bg=FIELD)
    dot.pack(side='left',padx=(0,12),anchor='n')
    textcol=tk.Frame(statusinner,bg=FIELD)
    textcol.pack(side='left',fill='x',expand=True)
    lbl(textcol,'STATUS DA CONVERSÃO',9,MUTED,True,bg=FIELD).pack(anchor='w')
    statuslabel=lbl(textcol,status.get(),12,TEXT,True,bg=FIELD)
    statuslabel.pack(anchor='w',pady=(4,2))
    detaillabel=lbl(textcol,detail.get(),9,MUTED,bg=FIELD)
    detaillabel.pack(anchor='w')
    status.trace_add('write',lambda *_:statuslabel.config(text=status.get()))
    detail.trace_add('write',lambda *_:detaillabel.config(text=detail.get()))

    actions=tk.Frame(inner,bg=SURFACE)
    actions.pack(fill='x',pady=(22,0))

    def open_path(key):
        path=last[key]
        if not path or not Path(path).exists():
            messagebox.showinfo('Arquivo indisponível','Converta um lote primeiro.',parent=root)
            return
        try:os.startfile(path)
        except Exception as exc:
            messagebox.showerror('Não foi possível abrir',str(exc),parent=root)

    def available_output_path(path):
        candidate=Path(path)
        base=candidate.stem
        def occupied(f):
            return any(q.exists() for q in (
                f,f.with_name(f.stem+'_CONFERENCIA.csv'),
                f.with_name(f.stem+'_PARCIAL_NAO_IMPRIMIR.pdf')))
        if not occupied(candidate):return candidate
        n=1
        while True:
            alternative=candidate.with_name(f'{base} ({n}){candidate.suffix}')
            if not occupied(alternative):return alternative
            n+=1

    def worker(src,dst,report):
        try:
            a,b,ok=create(src,dst,report)
            def finished():
                busy['value']=False
                convert_btn.config(state='normal',text='Converter etiquetas')
                last['csv']=report
                last['pdf']=dst if ok else str(Path(dst).with_name(Path(dst).stem+'_PARCIAL_NAO_IMPRIMIR.pdf'))
                if ok:
                    dot.config(fg=SUCCESS)
                    status.set('Conversão concluída')
                    detail.set(f'{a} etiquetas geradas  •  Nenhuma pendência')
                else:
                    dot.config(fg=WARNING)
                    status.set('Lote com pendências — não imprimir')
                    detail.set(f'{a} geradas  •  {b} pendências. Consulte o relatório.')
            root.after(0,finished)
        except Exception as exc:
            error=str(exc)
            def failed():
                busy['value']=False
                convert_btn.config(state='normal',text='Converter etiquetas')
                dot.config(fg=PINK)
                status.set('Não foi possível converter')
                detail.set(error[:105])
                messagebox.showerror('Erro na conversão',error,parent=root)
            root.after(0,failed)

    def convert():
        if busy['value']:return
        src=source.get().strip();dst=target.get().strip()
        if not src or not Path(src).is_file():
            messagebox.showwarning('PDF necessário','Selecione o PDF original do TikTok.',parent=root);return
        if not dst or Path(dst).suffix.lower()!='.pdf':
            messagebox.showwarning('Destino necessário','Escolha um destino PDF válido.',parent=root);return
        if Path(src).resolve()==Path(dst).resolve():
            messagebox.showwarning('Arquivos iguais','O PDF convertido não pode substituir o original.',parent=root);return
        dst=str(available_output_path(dst))
        target.set(dst)
        report=str(Path(dst).with_name(Path(dst).stem+'_CONFERENCIA.csv'))
        busy['value']=True
        convert_btn.config(state='disabled',text='Convertendo...')
        dot.config(fg=CYAN)
        status.set('Processando etiquetas...')
        detail.set('Aguarde. Não feche o aplicativo.')
        threading.Thread(target=worker,args=(src,dst,report),daemon=True).start()

    convert_btn=tk.Button(actions,text='Converter etiquetas',command=convert,
                          font=(FONT,11,'bold'),bg=CYAN,fg='#102124',
                          activebackground='#86E6E0',activeforeground='#102124',
                          relief='flat',bd=0,cursor='hand2',padx=21,pady=13)
    convert_btn.pack(side='left')
    for caption,key in [('Abrir PDF','pdf'),('Ver relatório','csv')]:
        tk.Button(actions,text=caption,command=lambda k=key:open_path(k),
                  font=(FONT,10),bg='#2A343E',fg=TEXT,
                  activebackground='#3B4853',activeforeground=TEXT,
                  relief='flat',bd=0,cursor='hand2',padx=15,pady=13).pack(side='left',padx=(9,0))

    footer=tk.Frame(shell,bg=BG)
    footer.pack(fill='x',pady=(17,0))
    lbl(footer,'QR compacto  •  Organização por SKU  •  Etiquetas 100 × 150 mm',
        9,MUTED,bg=BG).pack(side='left')
    lbl(footer,'Confira os códigos antes de imprimir',9,MUTED,bg=BG).pack(side='right')
    root.mainloop()

if __name__=='__main__':main()
