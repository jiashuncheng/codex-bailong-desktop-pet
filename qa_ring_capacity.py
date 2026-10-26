"""Render 1–6 layers at the real 121×102 logical-pixel card size."""
import sys,math,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'app'))
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase,QFont
from PySide6.QtWidgets import QApplication,QWidget,QGridLayout,QVBoxLayout,QLabel
from ring_widgets import QuotaRings,ring_geometry,AXIS_X,AXIS_Y,TILT

def main():
    app=QApplication([]);ident=QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc');app.setFont(QFont(QFontDatabase.applicationFontFamilies(ident)[0],10))
    root=QWidget();root.setStyleSheet('background:#fefcff;color:#463b59;');layout=QGridLayout(root);result={}
    for count in range(1,7):
        tile=QWidget();box=QVBoxLayout(tile);box.setContentsMargins(8,8,8,8);box.setSpacing(3)
        radii,stroke,badge=ring_geometry(count)
        title=QLabel(f'{count}环 · 图标{badge}px');title.setAlignment(Qt.AlignmentFlag.AlignCenter);title.setStyleSheet('font-family:"Microsoft YaHei UI";font-size:12px;font-weight:600;');box.addWidget(title)
        metrics=[dict(id=str(i),label='模拟',display='70%',kind=['quota','time','tokens'][i%3],icon=['calendar','clock','tokens','bolt'][i%4],progress=.7,description='仅为环数测试的模拟数据',low=False) for i in range(count)]
        rings=QuotaRings([],metrics=metrics);rings.setFixedWidth(121);box.addWidget(rings)
        gap=min(((radii[i]-radii[i+1])*min(AXIS_X,AXIS_Y)-badge for i in range(count-1)),default=None)
        note=QLabel('推荐：图标清晰' if count==3 else '图标偏小' if count==4 else '图标过小' if count>=5 else '空间宽裕');note.setAlignment(Qt.AlignmentFlag.AlignCenter);note.setStyleSheet('font-size:11px;');box.addWidget(note)
        result[str(count)]=dict(semiaxes=[[r*AXIS_X,r*AXIS_Y] for r in radii],tilt=TILT,stroke=stroke,icon_diameter=badge,minimum_badge_gap=gap)
        layout.addWidget(tile,(count-1)//3,(count-1)%3)
    root.show();app.processEvents();out=Path(__file__).parent/'验收截图/圆环容量';out.mkdir(parents=True,exist_ok=True)
    root.grab().save(str(out/'1至6环对比.png'));(out/'容量.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=True));root.close()
if __name__=='__main__':main()
