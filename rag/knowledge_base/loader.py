import json
from pathlib import Path


def load_knowledge_base():
    path = Path(__file__).parent / "knowledge_base.json"

    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


if __name__ == "__main__":
    documents = load_knowledge_base()

    print("Number of documents:", len(documents))

    for document in documents:
        print(document["id"], "-", document["title"])