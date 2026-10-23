"""Main entry point for Sputtering Design Tools."""
import argparse
from pathlib import Path
from panel_editor import PanelEditor


def main():
    parser = argparse.ArgumentParser(description='Frontal Eurorack 3U — Sputtering Design Tools')
    parser.add_argument('gerbers', nargs='*', help='Capas Gerber o ZIP de referencia')
    parser.add_argument('--project', help='Proyecto .panel.json guardado')
    parser.add_argument('--demo', action='store_true', help='Abrir el ejemplo sintético de demostración')
    args = parser.parse_args()
    project = Path(__file__).with_name('examples') / 'demo.panel.json' if args.demo else args.project
    PanelEditor(args.gerbers, project=project).mainloop()


if __name__ == '__main__':
    main()
