"""Regenerates docs/icons/*.png (green candlesticks on black). Requires Pillow. Dev-only."""
from PIL import Image, ImageDraw
def draw(size):
    S = 2048; im = Image.new("RGB", (S, S), "#000000"); d = ImageDraw.Draw(im); k = S / 512
    d.ellipse([56*k, 56*k, 456*k, 456*k], fill="#06130b")
    for x, wt, wb, bt, bb in ((170, 190, 340, 235, 310), (256, 160, 330, 200, 290), (342, 120, 300, 150, 250)):
        d.rectangle([(x-4)*k, wt*k, (x+4)*k, wb*k], fill="#00e676")
        d.rounded_rectangle([(x-22)*k, bt*k, (x+22)*k, bb*k], radius=6*k, fill="#00e676")
    d.rectangle([130*k, 366*k, 382*k, 374*k], fill="#0c4026")
    return im.resize((size, size), Image.LANCZOS)
if __name__ == "__main__":
    draw(192).save("docs/icons/icon-192.png"); draw(512).save("docs/icons/icon-512.png"); draw(512).save("docs/icons/icon-maskable-512.png")
