"""Post-process the macOS bundle's Info.plist: version, credits and document types (Open With / default app)."""
import plistlib
import sys

app, version = sys.argv[1], sys.argv[2]
path = f"{app}/Contents/Info.plist"
with open(path, "rb") as f:
    pl = plistlib.load(f)
pl.update({
    "CFBundleShortVersionString": version,
    "CFBundleVersion": version,
    "CFBundleDisplayName": "Frameline",
    "NSHumanReadableCopyright": "Designed and built by Miguel Rato",
    "NSHighResolutionCapable": True,
    "LSMinimumSystemVersion": "12.0",
    "CFBundleDocumentTypes": [
        {"CFBundleTypeName": "Video", "CFBundleTypeRole": "Viewer", "LSHandlerRank": "Alternate",
         "LSItemContentTypes": ["public.movie", "public.mpeg-4", "com.apple.quicktime-movie", "public.avi",
                                "org.matroska.mkv", "org.webmproject.webm", "public.mpeg",
                                "public.mpeg-2-transport-stream"]},
        {"CFBundleTypeName": "Image", "CFBundleTypeRole": "Viewer", "LSHandlerRank": "Alternate",
         "LSItemContentTypes": ["public.image", "com.ilm.openexr-image", "public.tiff"]},
        {"CFBundleTypeName": "Frameline Session", "CFBundleTypeRole": "Editor", "LSHandlerRank": "Owner",
         "CFBundleTypeExtensions": ["flsession"]},
    ],
})
with open(path, "wb") as f:
    plistlib.dump(pl, f)
print("Info.plist updated")
