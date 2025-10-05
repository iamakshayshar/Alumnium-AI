import pytest

def test_duckduckgo_search(al, driver, rp_logger, config):
    rp_logger.info("Start test: duckduckgo search via Alumnium")

    base = config.get("base_url", "https://duckduckgo.com")
    # navigate using Selenium driver (Alumnium typically relies on driver state)
    driver.get(base)

    # Use Alumnium high-level commands
    # Note: phrase instructions clearly for better determinism
    al.do("enter 'Mercury element' into the search input and submit")
    al.check("page title contains Mercury")
    rp_logger.info("Finished Alumnium-driven search test")
