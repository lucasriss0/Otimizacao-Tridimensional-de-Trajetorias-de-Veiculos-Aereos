"""Executa um modo de apresentação por vez no CoppeliaSim local."""

import argparse
from pathlib import Path
import sys
import tempfile


def main() -> None:
    import msvcrt

    parser = argparse.ArgumentParser(prog="apresentar.cmd", description=__doc__, allow_abbrev=False)
    parser.add_argument("cenario", nargs="?", choices=("serra_do_cipo", "monte_verde", "todos"))
    parser.add_argument("--novo", action="store_true", help="Executa somente o A*.")
    parser.add_argument("--objetos", action="store_true", help="Seleciona o cenário com 12 árvores.")
    args = parser.parse_args([argument.lower() for argument in sys.argv[1:]])
    if (args.objetos and args.cenario) or (args.novo and args.cenario == "todos"):
        parser.error("Escolha apenas um cenário. O modo todos exibe os dois métodos.")

    # O Windows libera o bloqueio ao fechar o arquivo, inclusive se o processo terminar.
    lock_path = Path(tempfile.gettempdir()) / "fho-ia-coppeliasim-23000.lock"
    with lock_path.open("a+b") as lock:
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            parser.exit(1, "Já existe um apresentar.cmd em execução. Aguarde o término e tente novamente.\n")

        if args.cenario == "todos":
            from src.scenario_presentation import main as show_all

            show_all([])
            return

        scenario = args.cenario or ("demo_obstacles" if args.objetos else "demo_coverage")
        options = ["--scenario", f"configs/{scenario}.yaml"]
        if args.novo:
            from src.coverage_comparison import main as fly

            fly([*options, "--proposed-only", "--executor", "lua"])
        else:
            from src.benchmark import main as compare

            compare([*options, "--disable-rendering", "--reuse-replay"])


if __name__ == "__main__":
    main()
