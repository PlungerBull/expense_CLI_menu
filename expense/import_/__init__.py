"""Spreadsheet import for the `expense import` command.

CLI-specific input handling (like dates.py): parses an .xlsx
client-side and feeds the existing engine write endpoints. No business logic
lives here — accounts/categories/hashtags are resolved-or-created by name and
transactions are sent through POST /v1/transactions/batch.
"""
