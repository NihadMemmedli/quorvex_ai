# CNN Smoke Test

Verify that the framework can successfully navigate to and interact with a public website.

## Test: Homepage Loads Successfully

**Purpose**: Validate basic navigation and page loading works

1. Navigate to https://cnn.com
2. Wait for page to load
3. Verify the page title contains "CNN"
4. Verify main content area is visible

---

## Test: Navigation Menu Works

**Purpose**: Validate element interaction works

1. Navigate to https://cnn.com
2. Find and click on a navigation link (e.g., "World", "Politics", "Business")
3. Verify the URL changes to include the selected section
4. Verify the page has content (articles, headlines)

---

## Test: Search Functionality

**Purpose**: Validate form interaction works

1. Navigate to https://cnn.com
2. Find the search input field
3. Type a search term (e.g., "news")
4. Submit the search
5. Verify search results page loads
