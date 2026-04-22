"""Generate icon.ico for BatteryMonitor.exe (called by build.ps1)."""
from PIL import Image, ImageDraw


def make_frame(size: int, pct: int = 80) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)
    c   = (60, 210, 60)
    s   = size / 64

    d.rectangle([int(4*s), int(16*s), int(54*s), int(52*s)],
                outline=c, width=max(1, int(3*s)))
    d.rectangle([int(54*s), int(28*s), int(60*s), int(40*s)], fill=c)

    fill_w = max(1, int(46 * s * pct / 100))
    d.rectangle([int(7*s), int(19*s), int(7*s) + fill_w, int(49*s)], fill=c)

    return img.convert("RGBA")


if __name__ == "__main__":
    frames = [make_frame(sz) for sz in (256, 128, 64, 48, 32, 16)]
    frames[0].save(
        "icon.ico",
        format="ICO",
        sizes=[(f.width, f.height) for f in frames],
        append_images=frames[1:],
    )
    print("icon.ico written")
