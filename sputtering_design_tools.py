"""Main entry point for Sputtering Design Tools."""
import argparse
from pathlib import Path
from panel_editor import PanelEditor
from design_app import DesignToolsApp


def main():
    parser = argparse.ArgumentParser(description='Frontal Eurorack 3U — Sputtering Design Tools')
    parser.add_argument('gerbers', nargs='*', help='Capas Gerber o ZIP de referencia')
    parser.add_argument('--project', help='Proyecto .panel.json guardado')
    parser.add_argument('--demo', action='store_true', help='Abrir el ejemplo sintético de demostración')
    parser.add_argument('--panel', action='store_true', help='Abrir solo el espacio de frontales (opcional)')
    args = parser.parse_args()
    project = Path(__file__).with_name('examples') / 'demo.panel.json' if args.demo else args.project
    app_class = PanelEditor if args.panel else DesignToolsApp
    app_class(args.gerbers, project=project).mainloop()


if __name__ == '__main__':
    main()
