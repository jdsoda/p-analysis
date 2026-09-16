# Register optional ITR Excel routes before app.py registers the ITR blueprint.
try:
    from itr_manager import itr
    from itr_excel_export import register
    register(itr)
except Exception:
    # Keep normal application startup unaffected if optional export setup fails.
    pass
