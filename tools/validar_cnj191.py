"""Valida a amostra DJ191/2026 e o exemplo manual, sem acessar envio ou clientes."""
import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("manual", type=Path)
    parser.add_argument("--output", type=Path, default=Path("output/validacao-cnj191"))
    args = parser.parse_args()
    pages = server.extract_pages(args.pdf.read_bytes())
    records = server.split_publications(pages)
    expected = {
        "0007073-76.2025.2.00.0000": [7], "0009578-40.2025.2.00.0000": [7, 8],
        "0002245-03.2026.2.00.0000": [8, 9], "0009859-06.2019.2.00.0000": [9],
        "0000029-25.2026.2.00.0823": [9], "0001973-77.2024.2.00.0000": [9, 10],
        "0005806-35.2026.2.00.0000": [10, 11, 12], "0009192-49.2021.2.00.0000": [12],
        "0001888-23.2026.2.00.0000": [12, 13, 14, 15], "0006456-82.2026.2.00.0000": [15, 16, 17],
    }
    assert len(pages) == 17 and len(records) == 15
    procedural = [r for r in records if r["processo"] in expected]
    assert len(procedural) == 10
    assert [r["paginas_origem"] for r in records[:5]] == [[2, 3, 4], [4, 5], [5], [6], [6, 7]]
    for record in procedural:
        assert record["paginas_origem"] == expected[record["processo"]]
        assert record["cabecalho"] == "Secretaria Geral\nSecretaria Processual\nPJE\nINTIMAÇÃO"
    sample = next(r for r in records if r["processo"] == "0002245-03.2026.2.00.0000")
    normalize = lambda text: re.sub(r"\s+", " ", text).strip()
    manual = normalize(args.manual.read_text(encoding="utf-8"))
    # O exemplo colado omite apenas a letra N do marcador inicial do PDF.
    manual = manual.replace("INTIMAÇÃO . 0002245", "INTIMAÇÃO N. 0002245", 1)
    assert normalize(sample["publicacao_integral"]) == manual, "Divergência do exemplo manual"
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "publicacao-exemplo.txt").write_text(sample["publicacao_integral"], encoding="utf-8")
    (args.output / "publicacoes.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {"paginas": len(pages), "publicacoes": len(records), "portarias": 5, "processuais": 10,
               "comparacao_manual": "Igual após normalizar espaços e restaurar N. do original",
               "envios_realizados": 0,
               "limites": [{"publicacao": r["processo"], "paginas": r["paginas_origem"], "limites": r["limites"]} for r in records]}
    (args.output / "validacao.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("OK: 15 publicações, 10 processos, 5 portarias; exemplo manual conferido; nenhum envio.")


if __name__ == "__main__":
    main()
