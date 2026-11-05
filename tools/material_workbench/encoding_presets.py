"""Explicit color-compression choices; alpha and pixel dimensions stay intact."""
PRESETS={
    'q95':dict(label='高清 Q95',description='细节优先，颜色轻微压缩',lossless=False,quality=95,method=4),
    'q90':dict(label='均衡 Q90',description='画质与体积折中',lossless=False,quality=90,method=4),
    'q85':dict(label='小体积 Q85',description='更小文件，建议检查脸部细节',lossless=False,quality=85,method=4),
    'lossless':dict(label='逐像素无损',description='像素完全一致，文件较大',lossless=True,quality=100,method=1),
}

def preset(code):
    if code not in PRESETS:raise ValueError('未知编码档位：'+str(code))
    return PRESETS[code]
