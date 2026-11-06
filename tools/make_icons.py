"""Gera os ícones PNG do PWA a partir da geometria do logo da Maré (duas ondas e a lua).
Mesma construção dos SVGs em static/logo. Uso: python tools/make_icons.py"""
from pathlib import Path
from PIL import Image, ImageDraw

SAIDA = Path(__file__).resolve().parent.parent / "static" / "icons"
ABISMO, BORDA = (3, 7, 20, 255), (23, 49, 92, 255)
ESPUMA, COBALTO, NEON = (219, 234, 243, 255), (25, 99, 166, 255), (34, 195, 230, 255)
ONDA1 = [((12, 60), (22, 48), (32, 48), (42, 58)), ((42, 58), (52, 68), (62, 64), (76, 48))]
ONDA2 = [((12, 78), (22, 66), (32, 66), (42, 76)), ((42, 76), (52, 86), (62, 82), (76, 66))]


def bezier(p, n=40):
    out = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        out.append((u**3 * p[0][0] + 3 * u * u * t * p[1][0] + 3 * u * t * t * p[2][0] + t**3 * p[3][0],
                    u**3 * p[0][1] + 3 * u * u * t * p[1][1] + 3 * u * t * t * p[2][1] + t**3 * p[3][1]))
    return out


def desenhar(tam: int, escala: float, centro_simbolo: bool, arredondar: bool, grosso: bool = False) -> Image.Image:
    ss = 4
    px = tam * ss / 96  # unidades do viewBox -> pixels
    img = Image.new("RGBA", (tam * ss, tam * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if arredondar:
        d.rounded_rectangle([0.5 * px, 0.5 * px, 95.5 * px, 95.5 * px], radius=22 * px, fill=ABISMO, outline=BORDA, width=max(1, int(px)))
    else:
        d.rectangle([0, 0, tam * ss, tam * ss], fill=ABISMO)
    if centro_simbolo:   # maskable: centraliza o símbolo (caixa 7,5-85 x 15-82) em 48,48
        tx, ty = 48 - escala * 46.25, 48 - escala * 48.5
    else:                # mesma translação do manual do logo
        tx, ty = 13.3, 9.9
    w, r = (11, 9) if grosso else (9, 8)
    T = lambda x, y: ((tx + escala * x) * px, (ty + escala * y) * px)
    for cor, segs in ((COBALTO, ONDA2), (ESPUMA, ONDA1)):
        pts = [T(*q) for s in segs for q in bezier(s, 120)]
        rr = w * escala * px / 2
        for q in pts:   # carimba círculos ao longo da curva: ponta redonda e sem falhas nas dobras
            d.ellipse([q[0] - rr, q[1] - rr, q[0] + rr, q[1] + rr], fill=cor)
    cx, cy = T(77, 23)
    rr = r * escala * px
    d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=NEON)
    return img.resize((tam, tam), Image.LANCZOS)


def main() -> None:
    SAIDA.mkdir(parents=True, exist_ok=True)
    desenhar(192, 0.75, False, True).save(SAIDA / "icon-192.png")
    desenhar(512, 0.75, False, True).save(SAIDA / "icon-512.png")
    desenhar(512, 0.58, True, False).save(SAIDA / "icon-maskable-512.png")
    desenhar(180, 0.66, True, False).save(SAIDA / "apple-touch-icon.png")
    desenhar(48, 0.75, False, True, grosso=True).save(SAIDA / "favicon-48.png")
    print("ok:", sorted(p.name for p in SAIDA.glob("*.png")))


if __name__ == "__main__":
    main()
