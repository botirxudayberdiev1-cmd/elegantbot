# To'y Reels montaj (9:16)

Kadrlar papkasidan Instagram Reels uchun 1080x1920 video yasaydi:

- musiqa ritmini (BPM) o'zi topadi, kadrlarni beat ustida kesadi;
- musiqaning eng kuchli qismini (naqarot) o'zi tanlaydi (`--music-start` bilan o'zgartirish mumkin);
- 50/60 fps videolarni haqiqiy slow-motion qiladi;
- rasmlarga Ken Burns (sekin yaqinlashish/uzoqlashish);
- iliq «to'y» rangi, vinyetka, film doni;
- o'tishlar: dissolve, oq chaqnash, smooth slide, circle, zoom, blur; tez kadrlarda — beatga kesish;
- boshida ism-sharif, oxirida studiya nomi; ovoz Instagram me'yori (-14 LUFS).

## O'rnatish

1. ffmpeg: https://www.gyan.dev/ffmpeg/builds/ (PATH'ga qo'shing)
2. `pip install -r montaj_reels/requirements.txt`

## Ishlatish

Kadrlarni bitta papkaga tartib bilan nomlab qo'ying (`01.mp4`, `02.jpg`, ...):

```
python montaj_reels/reels.py kadrlar --music musiqa.mp3 --title "Aziz & Madina" --subtitle "Wedding day" --duration 30 --out reels.mp4
```

- `--fit blur` — gorizontal kadr kesilmasin, xira fon ustida to'liq ko'rinsin
- `--preview` — tez sinov
- `--end ""` — oxirgi yozuvsiz

Instagram'dagi trend musiqani qo'shmoqchi bo'lsangiz, `--music` siz yasang va musiqani Instagram ichida qo'shing.
