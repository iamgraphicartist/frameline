"""Post-process a macOS bundle's Info.plist: version, credits and document types (Open With / default app).

Usage: python mac_plist.py dist/Frameline.app 1.0.0 [frameline|stillframe]
"""
import plistlib
import sys

app, version = sys.argv[1], sys.argv[2]
kind = sys.argv[3] if len(sys.argv) > 3 else "frameline"
path = f"{app}/Contents/Info.plist"
with open(path, "rb") as f:
    pl = plistlib.load(f)

if kind == "stillframe":
    name = "Stillframe"
    doc_types = [
        {"CFBundleTypeName": "Image", "CFBundleTypeRole": "Viewer", "LSHandlerRank": "Alternate",
         "LSItemContentTypes": ["public.image", "public.jpeg", "public.png", "public.heic", "public.heif",
                                "org.webmproject.webp", "com.compuserve.gif", "public.tiff", "public.avif",
                                "com.microsoft.bmp", "com.ilm.openexr-image", "public.svg-image"]},
    ]
else:
    name = "Frameline"
    doc_types = [
        {"CFBundleTypeName": "Video", "CFBundleTypeRole": "Viewer", "LSHandlerRank": "Alternate",
         "LSItemContentTypes": ["public.movie", "public.mpeg-4", "com.apple.quicktime-movie", "public.avi",
                                "org.matroska.mkv", "org.webmproject.webm", "public.mpeg",
                                "public.mpeg-2-transport-stream"]},
        {"CFBundleTypeName": "Image", "CFBundleTypeRole": "Viewer", "LSHandlerRank": "Alternate",
         "LSItemContentTypes": ["com.ilm.openexr-image", "public.tiff"]},
        {"CFBundleTypeName": "Frameline Session", "CFBundleTypeRole": "Editor", "LSHandlerRank": "Owner",
         "CFBundleTypeExtensions": ["flsession"]},
    ]

pl.update({
    "CFBundleShortVersionString": version,
    "CFBundleVersion": version,
    "CFBundleDisplayName": name,
    "NSHumanReadableCopyright": "Designed and built by Miguel Rato",
    "NSHighResolutionCapable": True,
    "LSMinimumSystemVersion": "12.0",
    "CFBundleDocumentTypes": doc_types,
})
with open(path, "wb") as f:
    plistlib.dump(pl, f)
print(f"{name} Info.plist updated")
