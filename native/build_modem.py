"""Build the original DSP engine for Windows, Linux (including ARM) or macOS."""
import os, subprocess, sys, shutil, shlex
from pathlib import Path
root=Path(__file__).resolve().parents[1]
out=root/'native'/'bin';out.mkdir(exist_ok=True)
if sys.platform != 'win32':
    if sys.platform != 'darwin' and not sys.platform.startswith('linux'):
        raise SystemExit('Unsupported modem build platform: '+sys.platform)
    compiler=shlex.split(os.environ.get('CXX','c++'))
    if not compiler or not shutil.which(compiler[0]):
        raise SystemExit('Install a C++17 compiler (g++ or Xcode command line tools).')
    mac=sys.platform=='darwin'
    target=out/('libpropview_modem.dylib' if mac else 'libpropview_modem.so')
    subprocess.run([*compiler,'-std=c++17','-O2','-fPIC','-dynamiclib' if mac else '-shared',str(root/'native/propview_modem.cpp'),'-o',str(target)],check=True)
    print(target)
    raise SystemExit(0)
vswhere=Path(os.environ.get('ProgramFiles(x86)','C:/Program Files (x86)'))/'Microsoft Visual Studio/Installer/vswhere.exe'
vs=subprocess.check_output([str(vswhere),'-latest','-products','*','-requires','Microsoft.VisualStudio.Component.VC.Tools.x86.x64','-property','installationPath'],text=True).strip()
if not vs: raise SystemExit('MSVC C++ build tools are required to build the development modem.')
vc=Path(vs)/'VC/Auxiliary/Build/vcvars64.bat'
batch=out/'compile.cmd'
batch.write_text('@echo off\ncall "'+str(vc)+'" >nul\nif errorlevel 1 exit /b 1\ncl /nologo /LD /O2 /EHsc /std:c++17 /MT "'+str(root/'native/propview_modem.cpp')+'" /link /OUT:"'+str(out/'propview_modem.dll')+'"\n',encoding='utf-8')
subprocess.run(['cmd','/c',str(batch)],cwd=out,check=True)
print(out/'propview_modem.dll')
