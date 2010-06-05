from distutils.core import setup
import py2exe
import py_compile

excludes = ["Secur32.dll", "SHFOLDER.dll"]
setup(
    options = {
        "py2exe": {
            "compressed": 1,
            "optimize": 2,
            "ascii": 1,
            "bundle_files": 1,
            "dll_excludes": excludes,
            "packages": ["encodings"],
            "dist_dir": "dist"
            }
        },
    zipfile = None,
    console=["pqdl.py"]
    )

