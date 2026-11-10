"""Main entry point for Sputtering Design Tools."""
import argparse
from pathlib import Path
from panel_editor import PanelEditor
from design_app import DesignToolsApp


def main():
    parser = argparse.ArgumentParser(description='Frontal Eurorack 3U — Sputtering Design Tools')
    parser.add_argument('gerbers', nargs='*', help='Capas Gerber o ZIP de referencia')
    parser.add_argument('--project', help='Módulo .module.json o proyecto .panel.json / .silk.json guardado')
    parser.add_argument('--board', help='Abrir una PCB Allegro como proyecto de serigrafía')
    parser.add_argument('--fabrication', help='ZIP exacto de liberación Allegro asociado a --board')
    parser.add_argument('--demo', action='store_true', help='Abrir el ejemplo sintético de demostración')
    parser.add_argument('--panel', action='store_true', help='Abrir solo el espacio de frontales (opcional)')
    args = parser.parse_args()
    if bool(args.board) != bool(args.fabrication):
        parser.error('--board y --fabrication deben usarse juntos para conservar la liberación exacta.')
    project = Path(__file__).with_name('examples') / 'demo.panel.json' if args.demo else args.project
    app_class = PanelEditor if args.panel else DesignToolsApp
    if args.board and args.panel:
        parser.error('--board abre el flujo de serigrafía; el frontal se ofrece desde esa ventana.')
    app = app_class(args.gerbers, project=project)
    if args.board:
        board, fabrication = args.board, args.fabrication
        app.after_idle(lambda: app.load_paths([board], fabrication=fabrication, offer_panel=True))
    app.mainloop()


if __name__ == '__main__':
    main()
