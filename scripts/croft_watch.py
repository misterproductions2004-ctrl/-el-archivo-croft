name: Croft Watch

on:
  workflow_dispatch:
  schedule:
    - cron: "30 */6 * * *"

permissions:
  contents: write

concurrency:
  group: croft-watch
  cancel-in-progress: false

jobs:
  monitor:
    runs-on: ubuntu-latest
    steps:
      - name: Descargar repositorio
        uses: actions/checkout@v4

      - name: Preparar Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: "pip"

      - name: Instalar dependencias
        run: |
          python -m pip install --upgrade pip
          pip install requests beautifulsoup4

      - name: Ejecutar Croft Watch
        run: python scripts/croft_watch.py

      - name: Guardar historial de vigilancia
        run: |
          git config user.name "croft-watch-bot"
          git config user.email "croft-watch-bot@users.noreply.github.com"
          git add data/croft_watch_seen.json data/archivo_croft_index.json
          git diff --cached --quiet || git commit -m "Actualizar historial de Croft Watch"
          git push

      - name: Subir informe editorial
        uses: actions/upload-artifact@v4
        with:
          name: croft-watch-review
          path: data/pendiente_revision.md
          retention-days: 30
