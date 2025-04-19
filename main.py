import asyncio
import json
import logging
import os
from typing import List, Optional
from urllib.parse import urlparse # Added for URL parsing

import pandas as pd
import tedata
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from selenium import webdriver # Added for the Firefox check

# Configure logging (respecting environment variable)
disable_logging = os.environ.get("TEDATA_DISABLE_LOGGING", "").lower() in (
    "true",
    "1",
    "yes",
)
tedata.configure(disable_logging=disable_logging)
logger = logging.getLogger("uvicorn.error")  # Use uvicorn's logger

# --- FastAPI App Initialization ---
app = FastAPI(
    title="Tedata OpenBB Backend",
    description="API backend to integrate tedata with OpenBB Workspace",
    version="1.0.0",
)

# --- CORS Configuration ---
origins = [
    "https://pro.openbb.co",
    "http://localhost",  # Allow local development
    "http://localhost:3000",  # Common local dev port for frontend
    "http://localhost:8000",  # Default uvicorn port
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Helper Functions ---


def run_tedata_search(search_term: str):
    """Synchronous wrapper for tedata search."""
    search = None # Initialize search to None
    try:
        search = tedata.search_TE(headless=True)
        search.search_trading_economics(search_term)
        if hasattr(search, "result_table") and isinstance(search.result_table, pd.DataFrame):
            results_df = search.result_table
            # Create the new indicator_id column by parsing the url column
            if 'url' in results_df.columns:
                results_df['indicator_id'] = results_df['url'].apply(_extract_id_from_url)
            else:
                results_df['indicator_id'] = None # Handle case where url column might be missing

            # Convert DataFrame to list of dictionaries (JSON serializable)
            results = results_df.to_dict(orient="records")
            return results
        else:
            logger.warning(f"Tedata search for {search_term} returned no result_table.")
            return []
    except Exception as e:
        logger.error(f"Error during tedata search for {search_term}: {str(e)}")
        # Raise the exception to be caught by the endpoint handler
        raise
    finally:
        # Ensure the webdriver is closed
        if search and hasattr(search, "driver"):
            try:
                # search_TE objects don't have a .close(), use driver.quit()
                if search.driver:
                    search.driver.quit()
            except Exception as e:
                logger.warning(f"Could not close/quit search webdriver: {str(e)}")


def run_tedata_scrape(indicator_id: str, method: str):
    """Synchronous wrapper for tedata scrape."""
    scraper = None  # Initialize scraper to None
    try:
        # Use the 'id' parameter as expected by tedata.scrape_chart
        scraper = tedata.scrape_chart(id=indicator_id, method=method, headless=True)
        if scraper and hasattr(scraper, "series") and isinstance(scraper.series, pd.Series):
            # Format the series into the desired JSON structure
            series_data = scraper.series.reset_index()
            series_data.columns = ["date", "value"]
            # Ensure date is formatted correctly and handle NaNs/NaTs
            series_data["date"] = series_data["date"].dt.strftime("%Y-%m-%d")
            # Convert NaN values to None (which becomes null in JSON)
            series_data["value"] = (
                series_data["value"]
                .astype(object)
                .where(pd.notnull(series_data["value"]), None)
            )

            results = series_data.to_dict(orient="records")
            return results
        elif scraper:
            # Attempt to get status or other info if series is missing
            scraper_status = (
                vars(scraper).get("_status", "N/A")
                if hasattr(scraper, "_status")
                else "Status unavailable"
            )
            logger.warning(
                f"Tedata scrape for {indicator_id} using method {method} "
                f"did not return a valid series. Scraper status: {scraper_status}"
            )
            return []
        else:
            logger.warning(
                f"Tedata scrape for {indicator_id} using method {method} "
                f"failed to initialize or run."
            )
            return []
    except Exception as e:
        logger.error(
            f"Error during tedata scrape for {indicator_id} using method {method}: {str(e)}"
        )
        # Raise the exception to be caught by the endpoint handler
        raise
    finally:
        # Ensure the webdriver is closed if scraper was initialized
        if scraper and hasattr(scraper, "driver"):
            try:
                scraper.close() # Use the close method to quit driver and cleanup
            except Exception as e:
                logger.warning(f"Could not close scrape webdriver: {str(e)}")


def run_tedata_metadata(indicator_id: str):
    """Synchronous wrapper for tedata metadata retrieval."""
    scraper = None  # Initialize scraper to None
    try:
        # We only need to scrape enough to get metadata, method doesn't matter much here
        # Using highcharts_api as it's often fastest if available
        scraper = tedata.scrape_chart(id=indicator_id, method="highcharts_api", headless=True)
        if scraper and hasattr(scraper, "metadata") and isinstance(scraper.metadata, dict):
            return scraper.metadata
        elif scraper:
            logger.warning(
                f"Tedata scrape for metadata ({indicator_id=}) did not return a valid metadata dictionary."
            )
            # Attempt fallback if primary method failed but object exists
            if not scraper.metadata:
                try:
                    logger.info(f"Attempting metadata scrape fallback for {indicator_id=}")
                    scraper.scrape_metadata() # Explicitly call metadata scraping
                    if scraper.metadata:
                        logger.info(f"Metadata fallback successful for {indicator_id=}")
                        return scraper.metadata
                except Exception as fallback_e:
                    logger.warning(f"Metadata fallback failed for {indicator_id=}: {str(fallback_e)}")
            return {}
        else:
            logger.warning(
                f"Tedata scrape for metadata ({indicator_id=}) failed to initialize or run."
            )
            return {}
    except Exception as e:
        logger.error(
            f"Error during tedata metadata retrieval for {indicator_id=}: {str(e)}"
        )
        # Raise the exception to be caught by the endpoint handler
        raise
    finally:
        # Ensure the webdriver is closed if scraper was initialized
        if scraper and hasattr(scraper, "driver"):
            try:
                scraper.close()  # Use the close method to quit driver and cleanup
            except Exception as e:
                logger.warning(f"Could not close metadata scrape webdriver: {str(e)}")


def _extract_id_from_url(potential_url: str) -> str:
    """Extracts country/indicator ID from a potential Trading Economics URL."""
    if potential_url and potential_url.startswith("http"):
        try:
            parsed = urlparse(potential_url)
            # Path is typically /country/indicator-name
            path_parts = parsed.path.strip("/").split("/")
            if len(path_parts) >= 2:
                # Rejoin the last two parts (or more if indicator name has slashes, unlikely)
                extracted_id = "/".join(path_parts)
                logger.debug(f"Extracted ID ", {extracted_id}, " from URL ", {potential_url})
                return extracted_id
        except Exception as e:
            logger.warning(f"Could not parse URL ", {potential_url}, " to extract ID: ", {str(e)})
    # If not a URL or parsing failed, assume it's already an ID
    return potential_url


def format_search_results_for_options(results: List[dict]) -> List[dict]:
    """Formats search results into the label/value structure for optionsEndpoint."""
    options = []
    if not results:
        return options
    for item in results:
        # Use title case for better readability in dropdown
        country = item.get("country", "N/A").title()
        metric = item.get("metric", "N/A").title()
        indicator_id = item.get("indicator_id") # Assumes indicator_id was added by run_tedata_search
        if indicator_id:
            options.append({
                # Combine country and metric for a descriptive label
                "label": f"{country} | {metric}",
                "value": indicator_id
            })
    return options


# --- API Endpoints ---


@app.get("/widgets.json")
async def get_widgets_config():
    """Serves the widgets.json configuration file."""
    try:
        with open("widgets.json", "r") as f:
            widgets_config = json.load(f)
        return JSONResponse(content=widgets_config)
    except FileNotFoundError:
        logger.error("widgets.json not found!")
        raise HTTPException(status_code=500, detail="Widget configuration file not found.")
    except json.JSONDecodeError:
        logger.error("widgets.json is not valid JSON!")
        raise HTTPException(
            status_code=500, detail="Widget configuration file is invalid."
        )
    except Exception as e:
        logger.error(f"Error reading widgets.json: {str(e)}")
        raise HTTPException(status_code=500, detail="Could not read widget configuration.")


@app.get("/search")
async def search_indicators(search_term: str = Query("US GDP", description="Term to search for")):
    """Searches Trading Economics indicators using tedata."""
    try:
        logger.info(f"Received search request for: {search_term}")
        # Run the synchronous tedata function in a separate thread
        results = await asyncio.to_thread(run_tedata_search, search_term)
        logger.info(f"Search for {search_term} returned {len(results)} results.")
        return JSONResponse(content=results)
    except Exception as e:
        logger.exception(f"Unhandled exception in /search for {search_term}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"An internal server error occurred during the search: {str(e)}",
        )


@app.get("/search-options")
async def search_indicators_options(search_term: str = Query("US GDP", description="Term to search for options")):
    """Searches TE indicators and formats them for an optionsEndpoint dropdown."""
    try:
        logger.info(f"Received search options request for: {search_term}")
        # Run the search (which also adds indicator_id)
        results_list = await asyncio.to_thread(run_tedata_search, search_term)
        # Format for options
        options = format_search_results_for_options(results_list)
        logger.info(f"Search options for {search_term} returned {len(options)} options.")
        return JSONResponse(content=options)
    except Exception as e:
        logger.exception(f"Unhandled exception in /search-options for {search_term}: {str(e)}")
        # Return empty list on error for options endpoint to prevent UI freezing
        return JSONResponse(content=[], status_code=500)


@app.get("/scrape")
async def scrape_indicator_data(
    # Accept search_term, which will contain the indicator ID or URL
    search_term: str = Query(
        "united-states/gdp",
        description="Indicator ID selected from search (e.g., united-states/gdp)",
    )
):
    """Scrapes time-series data for a specific Trading Economics indicator."""
    # valid_methods = ["highcharts_api", "path", "tooltips", "mixed"]
    # if method not in valid_methods:
    #     raise HTTPException(
    #         status_code=400,
    #         detail=f"Invalid method {method}. Valid methods are: {', '.join(valid_methods)}",
    #     )

    method = "highcharts_api"

    # Use the search_term as the potential ID/URL, extract the actual ID
    actual_indicator_id = _extract_id_from_url(search_term)

    if not actual_indicator_id or "/" not in actual_indicator_id:
        # Check the extracted ID format again after potential parsing
        raise HTTPException(
            status_code=400,
            detail=f"Invalid indicator ID format received from search_term: {actual_indicator_id}. Expected format: country/indicator-name.",
        )

    try:
        logger.info(
            f"Received scrape request for effective ID: {actual_indicator_id} (from search_term) with method: {method}"
        )
        # Run the synchronous tedata function in a separate thread
        results = await asyncio.to_thread(
            run_tedata_scrape, actual_indicator_id, method
        )
        logger.info(
            f"Scrape for {actual_indicator_id} ({method}) returned {len(results)} data points."
        )
        return JSONResponse(content=results)
    except Exception as e:
        logger.exception(
            f"Unhandled exception in /scrape for {actual_indicator_id} ({method}): {str(e)}"
        )
        raise HTTPException(
            status_code=500,
            detail=f"An internal server error occurred during scraping: {str(e)}",
        )


@app.get("/metadata")
async def get_indicator_metadata(
    # Accept search_term, which will contain the indicator ID or URL
    search_term: str = Query(
        "united-states/gdp",
        description="Indicator ID selected from search (e.g., united-states/gdp)",
    ),
):
    """Retrieves metadata for a specific Trading Economics indicator as Markdown."""
    # Use the search_term as the potential ID/URL, extract the actual ID
    actual_indicator_id = _extract_id_from_url(search_term)

    format_type = "pretty"

    if not actual_indicator_id or "/" not in actual_indicator_id:
        # Check the extracted ID format again after potential parsing
        raise HTTPException(
            status_code=400,
            detail=f"Invalid indicator ID format received from search_term: {actual_indicator_id}. Expected format: country/indicator-name.",
        )

    try:
        logger.info(
            f"Received metadata request for effective ID: {actual_indicator_id} (from search_term) with format: {format_type}"
        )
        # Run the synchronous tedata function in a separate thread
        metadata_dict = await asyncio.to_thread(
            run_tedata_metadata, actual_indicator_id
        )
        logger.info(f"Metadata request for {actual_indicator_id} successful.")

        if not metadata_dict:
            return PlainTextResponse(content="No metadata found.")

        # Format the dictionary based on the requested format type
        if format_type.lower() != "pretty":
            # Format the dictionary as a Markdown code block with JSON
            markdown_output = f"```json\n{json.dumps(metadata_dict, indent=2)}\n```"
            return PlainTextResponse(content=markdown_output)
        else:
            # Create pretty markdown dynamically from the JSON fields
            pretty_markdown_output = ""
            
            # Add title as main heading if available
            if "title" in metadata_dict:
                pretty_markdown_output += f"# {metadata_dict['title']}\n\n"
            
            # Fields that should be prominent (large headings)
            primary_fields = ["description"]
            for field in primary_fields:
                if field in metadata_dict:
                    pretty_markdown_output += f"## {field.replace('_', ' ').title()}\n\n{metadata_dict[field]}\n\n"
            
            # Fields for medium prominence (secondary headings)
            secondary_fields = ["country", "source", "original_source", "units", "frequency"]
            secondary_section = "## Key Information\n\n"
            for field in secondary_fields:
                if field in metadata_dict:
                    secondary_section += f"**{field.replace('_', ' ').title()}**: {metadata_dict[field]}\n\n"
            
            pretty_markdown_output += secondary_section
            
            # Numeric data section (dates and values)
            numeric_section = "## Data Range\n\n"
            date_value_fields = ["start_date", "end_date", "min_value", "max_value", "length"]
            for field in date_value_fields:
                if field in metadata_dict:
                    numeric_section += f"**{field.replace('_', ' ').title()}**: {metadata_dict[field]}\n\n"
            
            pretty_markdown_output += numeric_section
            
            # Add any remaining fields not already included
            remaining_fields = [
                field for field in metadata_dict 
                if field not in primary_fields 
                and field not in secondary_fields 
                and field not in date_value_fields
                and field != "title"
            ]
            
            if remaining_fields:
                remaining_section = "## Additional Information\n\n"
                for field in remaining_fields:
                    remaining_section += f"**{field.replace('_', ' ').title()}**: {metadata_dict[field]}\n\n"
                pretty_markdown_output += remaining_section
            
            return PlainTextResponse(content=pretty_markdown_output)

    except Exception as e:
        logger.exception(
            f"Unhandled exception in /metadata for {actual_indicator_id}: {str(e)}"
        )
        # Return error message as plain text for the markdown widget
        error_markdown = f"### Error\n\n```\nAn internal server error occurred during metadata retrieval: {str(e)}\n```"
        return PlainTextResponse(content=error_markdown, status_code=500)


# --- Optional: Add a root endpoint for health check/info ---
@app.get("/")
async def root():
    return {"message": "Tedata OpenBB Backend is running."}


# --- Uvicorn Entry Point (for running directly) ---
if __name__ == "__main__":
    import uvicorn

    # Check if Firefox is likely available before starting
    try:
        options = webdriver.FirefoxOptions()
        options.add_argument("--headless")
        driver = webdriver.Firefox(options=options)
        driver.quit()
        logger.info("Firefox check successful.")
    except Exception as ff_err:
        logger.error("-----------------------------------------------------")
        logger.error(" ERROR: Could not initialize Firefox WebDriver.")
        logger.error(" Please ensure Firefox is installed and accessible ")
        logger.error(" in your system's PATH.")
        logger.error(f" Details: {str(ff_err)}")
        logger.error(" The backend may not function correctly.")
        logger.error("-----------------------------------------------------")
        # Optionally, exit if Firefox is critical
        # import sys
        # sys.exit(1)

    # Get port from environment variable or default to 8000
    port = int(os.environ.get("PORT", 8000))
    # Get host from environment variable or default to 0.0.0.0
    host = os.environ.get("HOST", "0.0.0.0")

    uvicorn.run(app, host=host, port=port) 