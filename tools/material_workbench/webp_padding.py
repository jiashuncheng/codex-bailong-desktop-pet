"""Add transparent canvas space without recompressing animated WebP pixels.

Container layout: https://developers.google.com/speed/webp/docs/riff_container
Only VP8X canvas and ANMF offsets change; compressed frame payloads stay intact.
"""
from pathlib import Path
import os,struct
from PIL import Image

def u24(value):
    if not 0<=value<=0xffffff:raise ValueError('WebP24位字段越界')
    return int(value).to_bytes(3,'little')

def pad_webp(source,dest,side,shift):
    source=Path(source);dest=Path(dest)
    with Image.open(source) as im:
        width,height=im.size;count=getattr(im,'n_frames',1)
    if width+2*shift!=side or height+2*shift!=side or shift%2:
        raise ValueError('WebP留白需要对称偶数像素偏移')
    if shift==0:
        import shutil;shutil.copy2(source,dest);return dict(frames=count,container_only=True)
    if count<2:
        with Image.open(source) as im:
            frame=im.convert('RGBA');out=Image.new('RGBA',(side,side));out.paste(frame,(shift,shift));out.save(dest,lossless=True)
        return dict(frames=1,container_only=False)
    raw=bytearray(source.read_bytes())
    if raw[:4]!=b'RIFF' or raw[8:12]!=b'WEBP' or int.from_bytes(raw[4:8],'little')+8!=len(raw):raise ValueError('无效WebP容器')
    pos=12;seen_header=False;frames=0
    while pos<len(raw):
        if pos+8>len(raw):raise ValueError('WebP块头不完整')
        tag=bytes(raw[pos:pos+4]);size=int.from_bytes(raw[pos+4:pos+8],'little');offset=pos+8
        if offset+size>len(raw):raise ValueError('WebP块数据不完整')
        if tag==b'VP8X':
            if size!=10:raise ValueError('不支持的VP8X块')
            raw[offset]|=0x10
            raw[offset+4:offset+7]=u24(side-1);raw[offset+7:offset+10]=u24(side-1);seen_header=True
        elif tag==b'ANIM':
            if size!=6 or raw[offset+3]!=0:raise ValueError('需要透明动画背景')
        elif tag==b'ANMF':
            if size<16:raise ValueError('不完整的动画帧')
            x=int.from_bytes(raw[offset:offset+3],'little')+shift//2
            y=int.from_bytes(raw[offset+3:offset+6],'little')+shift//2
            fw=int.from_bytes(raw[offset+6:offset+9],'little')+1
            fh=int.from_bytes(raw[offset+9:offset+12],'little')+1
            if x*2+fw>side or y*2+fh>side:raise ValueError('移动帧越过新画布')
            raw[offset:offset+3]=u24(x);raw[offset+3:offset+6]=u24(y);frames+=1
        pos=offset+size+(size%2)
    if not seen_header or frames!=count:raise ValueError('WebP动画帧数不匹配')
    dest.parent.mkdir(parents=True,exist_ok=True);temp=dest.with_name(dest.name+'.tmp');temp.write_bytes(raw);os.replace(temp,dest)
    return dict(frames=frames,container_only=True)
