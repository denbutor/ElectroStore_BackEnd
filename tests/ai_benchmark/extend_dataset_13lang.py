import json
from pathlib import Path


NEW_CASES: list[dict] = [
    {
        "id": "E5",
        "category": "multilingual_ui",
        "language": "it",
        "expected_ui_lang": "it",
        "prompt": "Quale scheda video consigli per giocare in 1440p e quali modelli avete disponibili in ElectroStore?",
        "ground_truth_facts": [
            "Відповідь італійською мовою",
            "Початок із маркера [[UI_LANG:it]]",
            "Згадка наявних моделей RTX 4070 Super ($599) або RTX 4070 Ti Super ($799)",
        ],
    },
    {
        "id": "E6",
        "category": "multilingual_ui",
        "language": "nl",
        "expected_ui_lang": "nl",
        "prompt": "Welke NVIDIA videokaarten hebben jullie op voorraad in ElectroStore en wat zijn de prijzen in dollars?",
        "ground_truth_facts": [
            "Відповідь нідерландською мовою",
            "Початок із маркера [[UI_LANG:nl]]",
            "Коректні ціни в $ та залишки з каталогу",
        ],
    },
    {
        "id": "E7",
        "category": "multilingual_ui",
        "language": "da",
        "expected_ui_lang": "da",
        "prompt": "Hvilken processor anbefaler du til gaming fra ElectroStore kataloget, og hvad koster den?",
        "ground_truth_facts": [
            "Відповідь данською мовою",
            "Початок із маркера [[UI_LANG:da]]",
            "Ціна в $ і реальна модель з каталогу",
        ],
    },
    {
        "id": "E8",
        "category": "multilingual_ui",
        "language": "sv",
        "expected_ui_lang": "sv",
        "prompt": "Har ni någon OLED-skärm med 240Hz i lager hos ElectroStore och vad är priset?",
        "ground_truth_facts": [
            "Відповідь шведською мовою",
            "Початок із маркера [[UI_LANG:sv]]",
            "ASUS ROG Swift OLED PG27AQDM 27-inch ($799, 6 шт.)",
        ],
    },
    {
        "id": "E9",
        "category": "multilingual_ui",
        "language": "cs",
        "expected_ui_lang": "cs",
        "prompt": "Jaký napájecí zdroj z nabídky ElectroStore doporučujete pro výkonnou herní sestavu?",
        "ground_truth_facts": [
            "Відповідь чеською мовою",
            "Початок із маркера [[UI_LANG:cs]]",
            "Corsair RM850e 850W ATX 3.1 PSU ($129)",
        ],
    },
    {
        "id": "E10",
        "category": "multilingual_ui",
        "language": "fi",
        "expected_ui_lang": "fi",
        "prompt": "Onko teillä Apple iPhone 16 Pro varastossa ElectroStoressa ja mikä sen hinta on?",
        "ground_truth_facts": [
            "Відповідь фінською мовою",
            "Початок із маркера [[UI_LANG:fi]]",
            "Apple iPhone 16 Pro 256GB ($1099, 15 шт.)",
        ],
    },
    {
        "id": "E11",
        "category": "multilingual_ui",
        "language": "no",
        "expected_ui_lang": "no",
        "prompt": "Hvilke prosessorer fra AMD eller Intel har dere på lager i ElectroStore akkurat nå?",
        "ground_truth_facts": [
            "Відповідь норвезькою мовою",
            "Початок із маркера [[UI_LANG:no]]",
            "Наявні CPU з каталогу та ціни в $",
        ],
    },
    {
        "id": "D5",
        "category": "out_of_catalog",
        "language": "uk",
        "expected_ui_lang": "uk",
        "prompt": "Чи є у вас в ElectroStore відеокарта RTX 5090 за $500 і скільки штук на складі?",
        "ground_truth_facts": [
            "Відмова: RTX 5090 за $500 відсутня в каталозі",
            "Пропозиція наявних флагманських відеокарт з актуальними цінами в $",
        ],
    },
    {
        "id": "F5",
        "category": "noisy_typos",
        "language": "en",
        "expected_ui_lang": "en",
        "prompt": "yo need a good 1440p monitor under 300 bucks what u got in stock rn?",
        "ground_truth_facts": [
            "Gigabyte M27Q 27-inch QHD 170Hz ($259)",
            "Ціна в $ та підтвердження наявності",
        ],
    },
]


def main() -> None:
    base_path = Path("benchmark_dataset.json")
    out_path = Path("benchmark_dataset_13lang.json")

    base_items = json.loads(base_path.read_text(encoding="utf-8"))
    seen_ids = {item["id"] for item in base_items}

    merged = list(base_items)
    added_count = 0
    for item in NEW_CASES:
        if item["id"] not in seen_ids:
            merged.append(item)
            seen_ids.add(item["id"])
            added_count += 1

    out_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Created {out_path.name}: {len(base_items)} base + {added_count} new = {len(merged)} total items.")


if __name__ == "__main__":
    main()