name: Bayse Price Comparison Diagnostic (temporary)

on:
  workflow_dispatch:
    inputs:
      search_id:
        description: 'An event ID (or part of one) to search for'
        required: true
        default: 'bfb44828-bff5-4a47-98bb-b21c2ab947ae'

jobs:
  diagnose:
    runs-on: ubuntu-latest
    timeout-minutes: 3
    steps:
      - name: Check out the code
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Compare list vs detail endpoint
        run: python compare_diagnostic.py
        env:
          BAYSE_PUBLIC_KEY: ${{ secrets.BAYSE_PUBLIC_KEY }}
          SEARCH_ID: ${{ inputs.search_id }}
