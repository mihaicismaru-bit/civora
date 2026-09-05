from __future__ import annotations
from pathlib import Path
import json, zipfile
from public_presence_os.control import build_source_manifest, manifest_hash

def main():
    root=Path(__file__).resolve().parents[1]
    out=root/"dist"; out.mkdir(exist_ok=True)
    manifest=build_source_manifest(root)
    mh=manifest_hash(manifest)
    manifest_path=out/"SOURCE_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    zip_path=out/f"public-presence-os-cp30-{mh[:12]}.zip"
    files=[root/p for p in manifest["files"]]
    with zipfile.ZipFile(zip_path,"w",compression=zipfile.ZIP_DEFLATED) as z:
        for path in files:
            rel=str(path.relative_to(root))
            info=zipfile.ZipInfo(rel,date_time=(1980,1,1,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o100644 << 16
            z.writestr(info,path.read_bytes())
        info=zipfile.ZipInfo("SOURCE_MANIFEST.json",date_time=(1980,1,1,0,0,0))
        info.compress_type=zipfile.ZIP_DEFLATED
        info.external_attr=0o100644 << 16
        z.writestr(info,manifest_path.read_bytes())
    print(json.dumps({"zip":str(zip_path),"manifest_hash":mh},sort_keys=True))

if __name__=="__main__":
    main()
