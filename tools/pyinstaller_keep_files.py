"""Fresh-path local build: refuse recursive cleanup even inside PyInstaller."""
import sys,shutil
from unittest.mock import patch
import PyInstaller.__main__

def refuse(*args,**kwargs):
    raise RuntimeError('Recursive deletion is not authorized; build files retained.')

with patch.object(shutil,'rmtree',side_effect=refuse):
    PyInstaller.__main__.run(sys.argv[1:])
