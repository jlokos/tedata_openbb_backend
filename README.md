

# TedataBB

Trading Economics data backend to be used by OpenBB Workspace.

![2025-04-18 at 01 34 31@2x](https://github.com/user-attachments/assets/ee43468c-5dfd-4bdd-8727-df1fe1b777ce)
## Getting Started

This custom backend provides access to Trading Economics data from within the OpenBB Workspace platform, allowing you to search and visualize economic indicators.

### Prerequisites

- Python 3.8+
- Firefox browser installed (required by tedata)

### Installation

1. Clone this repository:
```bash
git clone https://github.com/jlokos/tedata_openbb_backend.git
cd tedata_openbb_backend
```

2. Create a virtual environment and install the dependencies:
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Running

### Environment Variables

You can customize the behavior using these environment variables:

```
TEDATA_DISABLE_LOGGING=true  # Disable detailed tedata logging
```

Start the FastAPI server:

```bash
uvicorn main:app --reload --port 8000
```
---
### Integrating with OpenBB

Go into OpenBB Workspace at [https://pro.openbb.co/](https://pro.openbb.co/) and add this custom backend.

- Name: TedataBB
- URL: http://127.0.0.1:8000

If all is working, you can click "Test" and get confirmation of how many widgets are valid.

## Features

### Search Widget

Search for economic indicators across Trading Economics database:
- Search by country, indicator name, or other keywords
- View search results in a table format

### Scrape Widget

Extract time-series data for selected economic indicators:
- Supports multiple scraping methods (highcharts_api, path, tooltips, mixed)
- Retrieves historical data points
- Presents data in a table format ready for analysis

### Metadata Widget

View detailed metadata for any economic indicator:
- See full description, source, latest values
- View update frequency and other important information
- Choose between pretty formatted view and raw JSON format

## Known TODOs

- Search functionality needs improvement to allow grouping by indicator_id
- When clicking an indicator ID in search results, it should copy to clipboard rather than populating the search widget

## Repo Structure

### main.py

The main entry point for the FastAPI application that:
- Creates a FastAPI instance with API documentation
- Configures CORS middleware for cross-origin requests
- Implements endpoint handlers for searching and scraping data
- Provides utility functions for data extraction and formatting

### widgets.json

Defines the widget configurations recognized by OpenBB Workspace:
- Parameter definitions
- Widget size recommendations
- Descriptions and documentation
- Category assignments for organization

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Acknowledgment

- [tedata](https://github.com/HelloThereMatey/tedata)




