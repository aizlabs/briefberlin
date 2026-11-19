"""Optional real Anki importer check; run with a Python environment containing anki.

No personal collection is opened. Uses the production serializer and a disposable
collection. See docs/my-words-implementation-progress.md for validation evidence.
"""

import json
import subprocess
import tempfile
from importlib.metadata import version
from pathlib import Path

from anki.collection import Collection
from anki.import_export_pb2 import ImportCsvRequest

ROOT = Path(__file__).resolve().parents[2]


def main():
    with tempfile.TemporaryDirectory(prefix="briefberlin-anki-qa-") as folder:
        export_path = Path(folder) / "words.txt"
        generated = subprocess.check_output(
            ["node", "-e", """
const e = require('./output/assets/js/my-words-export.js');
console.log(e.anki([
  {term: 'die Änderung', translation: 'change, "revision"', explanation: 'Eine Änderung.\\nДругая строка\\tmehr', articleTitle: 'Regeln & Neues', articleUrl: 'https://briefberlin.de/articles/regeln/'},
  {term: 'beantragen', translation: 'to apply', explanation: 'Einen Antrag stellen.', articleTitle: 'Anträge', articleUrl: 'https://briefberlin.de/articles/antraege/'}
]));
"""], cwd=ROOT, text=True,
        )
        export_path.write_text(generated, encoding="utf-8")
        collection = Collection(str(Path(folder) / "collection.anki2"))
        try:
            metadata = collection.get_csv_metadata(str(export_path), None)
            assert list(metadata.global_notetype.field_columns) == [1, 2]
            assert metadata.is_html
            request = ImportCsvRequest(path=str(export_path), metadata=metadata)
            collection.import_csv(request)
            notes = [collection.get_note(nid).fields for nid in collection.find_notes("")]
            assert len(notes) == 2
            note = next(fields for fields in notes if fields[0] == "die Änderung")
            assert "Другая строка" in note[1]
            assert 'href="https://briefberlin.de/articles/regeln/"' in note[1]
            assert "&quot;revision&quot;" in note[1]
            collection.import_csv(request)
            assert len(collection.find_notes("")) == 2
            assert len(collection.find_cards("")) == 2
            print(json.dumps({"anki_version": version("anki"), "notes": 2, "cards": 2, "repeat_import": "no duplicates"}))
        finally:
            collection.close()


if __name__ == "__main__":
    main()
