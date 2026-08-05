# Soubory pro home-assistant/brands (volitelné)

**Tuto složku už většinou nepotřebuješ.** Od Home Assistantu 2026.3 si
integrace nese ikonu sama v `custom_components/koupaliste_lhotka/brand/`
a lokální obrázky mají přednost před centrálním repozitářem.

Složka tu zůstává pro dva případy:

* uživatelé na Home Assistantu starším než 2026.3 — těm se ikona zobrazí
  jen tehdy, když je v repozitáři [home-assistant/brands](https://github.com/home-assistant/brands),
* zařazení do veřejného seznamu HACS, které ikonu v brands vyžaduje.

```
brands/
└── custom_integrations/
    └── koupaliste_lhotka/
        ├── icon.png       256 × 256
        ├── icon@2x.png    512 × 512
        ├── logo.png       512 × 136
        └── logo@2x.png    1024 × 272
```

Postup, pokud to chceš udělat:

1. Forkni `home-assistant/brands`
2. Zkopíruj `custom_integrations/koupaliste_lhotka/` do stejné cesty ve forku
3. Otevři pull request

Soubory jsou totožné s těmi v `brand/` a splňují specifikaci: PNG
s průhledností, přesné rozměry, název složky odpovídá `domain` z
`manifest.json`.

Zdrojová SVG pro případné úpravy jsou v `../docs/icon.svg` a `../docs/logo.svg`.
