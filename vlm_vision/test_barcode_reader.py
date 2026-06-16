import sys, time
import numpy as np
from local_agent.traceability.barcode_reader import (
    BarcodeResult, CameraBarcodeReader, ScannerBarcodeReader, BarcodeReader,
)

_p=_f=0
def check(n,c,d=""):
    global _p,_f; _p+=c; _f+=(not c); print(f"  [{'PASS' if c else 'FAIL'}] {n}"+(f"  ({d})" if d else ""))

def make_barcode_image(value):
    import barcode
    from barcode.writer import ImageWriter
    from io import BytesIO
    from PIL import Image
    code = barcode.get('code128', value, writer=ImageWriter())
    buf = BytesIO(); code.write(buf); buf.seek(0)
    return np.array(Image.open(buf).convert('RGB'))

# ---- BarcodeResult ----
print("BarcodeResult")
r = BarcodeResult(value="SKU-1", source="scanner", timestamp=123.0)
check("value/source/timestamp set", r.value=="SKU-1" and r.source=="scanner" and r.timestamp==123.0)
check("confidence defaults to 1.0", r.confidence==1.0)
check("bbox defaults to None", r.bbox is None)
check("__str__ includes value", "SKU-1" in str(r))

# ---- CameraBarcodeReader: real decode ----
print("\nCameraBarcodeReader.read_frame (real barcode)")
cam = CameraBarcodeReader()
img = make_barcode_image("0687456223537")
out = cam.read_frame(img, timestamp=999.0)
check("decoded exactly one barcode", len(out)==1, f"{len(out)} results")
if out:
    b = out[0]
    check("decoded value correct", b.value=="0687456223537", b.value)
    check("source is camera", b.source=="camera")
    check("timestamp passed through", b.timestamp==999.0)
    check("camera confidence < 1.0 (0.95)", b.confidence==0.95)
    check("bbox present, 4 numbers", isinstance(b.bbox, list) and len(b.bbox)==4, str(b.bbox))
    x1,y1,x2,y2 = b.bbox
    check("bbox is sane (x2>x1, y2>y1)", x2>x1 and y2>y1)

print("\nCameraBarcodeReader edge cases")
blank = np.full((200,200,3), 255, np.uint8)
check("blank frame -> no results, no crash", cam.read_frame(blank)==[])
black = np.zeros((100,100,3), np.uint8)
check("black frame -> no results", cam.read_frame(black)==[])
out_nots = cam.read_frame(img)
check("no timestamp -> auto-filled (>0)", len(out_nots)==1 and out_nots[0].timestamp>0)

# ---- read_cropped ----
print("\nCameraBarcodeReader.read_cropped")
big = np.full((600,800,3),255,np.uint8)
bh,bw = img.shape[:2]
oy,ox = 100,100
big[oy:oy+bh, ox:ox+bw] = img
cropped = cam.read_cropped(big, [ox,oy,ox+bw,oy+bh], timestamp=5.0)
check("decodes from a cropped region", len(cropped)==1 and cropped[0].value=="0687456223537", str([c.value for c in cropped]))
edge = cam.read_cropped(big, [0,0,50,50])
check("edge crop clamps without crashing", isinstance(edge, list))
bad = cam.read_cropped(big, [9999,9999,10000,10000])
check("out-of-bounds bbox -> [] not crash", bad==[])

# ---- ScannerBarcodeReader ----
print("\nScannerBarcodeReader")
got = []
sc = ScannerBarcodeReader(on_scan=lambda r: got.append(r))
res = sc.simulate_scan("SCAN-42")
check("simulate_scan fires callback", len(got)==1 and got[0].value=="SCAN-42")
check("simulate_scan returns the result", res.value=="SCAN-42")
check("scanner source is 'scanner'", got[0].source=="scanner")
check("scanner confidence 1.0", got[0].confidence==1.0)

# ---- BarcodeReader (combined) ----
print("\nBarcodeReader (combined)")
br = BarcodeReader()
br.simulate_scanner_scan("BOX-7")
br.simulate_scanner_scan("BOX-8")
log = br.get_scan_log()
check("default handler logs scans", len(log)==2 and log[0].value=="BOX-7")
check("get_scan_log returns a copy", br.get_scan_log() is not log)

custom=[]
br2 = BarcodeReader(on_scan=lambda r: custom.append(r.value))
br2.simulate_scanner_scan("CUSTOM-1")
check("custom on_scan callback used", custom==["CUSTOM-1"])
check("custom handler -> default log stays empty", br2.get_scan_log()==[])

camres = br.read_from_frame(img, timestamp=7.0)
check("BarcodeReader.read_from_frame decodes", len(camres)==1 and camres[0].value=="0687456223537")
camcrop = br.read_from_frame_cropped(big, [ox,oy,ox+bw,oy+bh])
check("BarcodeReader.read_from_frame_cropped decodes", len(camcrop)==1 and camcrop[0].value=="0687456223537")

print(f"\n  RESULTS: {_p} passed, {_f} failed")
sys.exit(1 if _f else 0)