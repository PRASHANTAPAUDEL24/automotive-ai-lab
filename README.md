# Automotive AI Lab

Portfolio project building AI-powered analytics for automotive dealer
operations using a fully synthetic dataset for the fictional brand
"Vertex Motors". No real company data is used.

## Business Problem

Regional managers need to quickly identify underperforming dealers,
sales gaps, aging inventory, and potential stock risks.

This project starts with dealer analytics and will progressively add
APIs, databases, LLMs, RAG, agents, and cloud deployment.

## Dataset

Synthetic automotive data for 40 dealers across 24 months.

The dataset includes:

- Dealer information
- Vehicle models
- Monthly sales
- Dealer targets
- Monthly leads and test drives
- Inventory snapshot

## Progress
- [x] Day 1: September dealer performance vs. target (pandas)
- [x] Day 2: Same report in plain Python (csv module), with data-integrity check
- [x] Day 3: Inventory aging, months of supply, overstock flags
- [ ] Day 4: Combined dealer scorecard
- [ ] Week 2: SQL and PostgreSQL
- [ ] Week 3: FastAPI
- [ ] Week 4: Automotive Dealer Analytics API
- [ ] Later: LLM APIs, RAG, agents, Docker, Azure

## Project structure
- `scripts/generate_dealer_data.py` creates the synthetic dataset
- `data/` holds the generated CSV files
- `src/` holds the analysis scripts, one per day

## How to run
```
pip install -r requirements.txt
python scripts/generate_dealer_data.py
python src/day3_inventory_aging.py
```

## Definitions
- Available inventory: vehicles with status "In Stock" (excludes In Transit and Hold)
- Aged: more than 90 days in stock
- Overstock candidate: more than 4 months of supply and more than 30% aged

## Sample findings (September 2026, synthetic data)
- 12 of 40 dealers are below 80% of their sales target
- 9 dealers are flagged as overstock candidates
