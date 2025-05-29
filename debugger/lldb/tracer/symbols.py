def symbol_renderer(symbols):
    """
    Render symbols data as an interactive HTML page with sorting and filtering capabilities.
    Returns a Flask response with the HTML content.
    """
    if not symbols:
        return "<div>No symbols data available</div>"

    html = """
<!DOCTYPE html>
<html>
<head>
    <title>Symbols Viewer</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.datatables.net/1.13.5/css/dataTables.bootstrap5.min.css" rel="stylesheet">
    <style>
        .symbol-table { font-family: monospace; font-size: 0.9em; }
        .module-header { background-color: #f8f9fa; cursor: pointer; }
        .symbol-details { display: none; }
        .address { color: #6c757d; }
        .source-info { color: #0d6efd; }
        .symbol-content {
            font-family: monospace;
            white-space: pre;
            background-color: #f8f9fa;
            padding: 10px;
            border-radius: 5px;
        }
        .dataTables_wrapper .dataTables_paginate .paginate_button { padding: 0.3em 0.8em; }
    </style>
</head>
<body>
    <div class="container-fluid mt-3">
        <h3>Symbols Viewer</h3>
        <div class="mb-3">
            <input type="text" id="globalSearch" class="form-control" placeholder="Search all symbols...">
        </div>
        <div class="accordion" id="modulesAccordion">
"""

    for module_name, module_data in symbols.items():
        has_symbol_details = "symbol_details" in module_data and module_data["symbol_details"]
        symbol_count = len(module_data["symbol_details"]) if has_symbol_details else 0

        if not has_symbol_details:
            continue

        html += f"""
            <div class="accordion-item">
                <h2 class="accordion-header" id="heading{module_name}">
                    <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse"
                            data-bs-target="#collapse{module_name}" aria-expanded="false"
                            aria-controls="collapse{module_name}">
                        {module_name} (Symbols: {symbol_count})
                    </button>
                </h2>
                <div id="collapse{module_name}" class="accordion-collapse collapse"
                    aria-labelledby="heading{module_name}" data-bs-parent="#modulesAccordion">
                    <div class="accordion-body">
                        <table class="table table-sm table-hover symbol-table" id="table{module_name}">
                            <thead>
                                <tr>
                                    <th>Name</th>
                                    <th>Type</th>
                                    <th>Address Range</th>
                                    <th>Source Location</th>
                                </tr>
                            </thead>
                            <tbody>
        """

        for symbol in module_data["symbol_details"]:
            source_info = ""
            if "source" in symbol:
                source_info = f"{symbol['source']['file']}:{symbol['source']['line']}"

            html += f"""
                                <tr>
                                    <td>{symbol["name"]}</td>
                                    <td>{symbol["type"]}</td>
                                    <td class="address">
                                        {symbol["start_addr"]}
                                        {f"→ {symbol['end_addr']}" if symbol["end_addr"] else ""}
                                    </td>
                                    <td class="source-info">{source_info}</td>
                                </tr>
            """

        html += """
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        """

    html += """
        </div>
    </div>

    <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script src="https://cdn.datatables.net/1.13.5/js/jquery.dataTables.min.js"></script>
    <script src="https://cdn.datatables.net/1.13.5/js/dataTables.bootstrap5.min.js"></script>
    <script>
        $(document).ready(function() {
            // Initialize DataTables for each module table with enhanced options
            $('.symbol-table').each(function() {
                $(this).DataTable({
                    pageLength: 20,
                    lengthMenu: [10, 20, 50, 100, 200],
                    searching: true,
                    stateSave: true,
                    deferRender: true,
                    processing: true,
                    responsive: true,
                    dom: '<"top"lf>rt<"bottom"ip>',
                    language: {
                        search: "_INPUT_",
                        searchPlaceholder: "Search symbols...",
                        lengthMenu: "Show _MENU_ symbols per page",
                        info: "Showing _START_ to _END_ of _TOTAL_ symbols",
                        infoEmpty: "No symbols available",
                        infoFiltered: "(filtered from _MAX_ total symbols)"
                    },
                    columnDefs: [
                        { targets: [0,1,2,3], orderable: true },
                        { targets: '_all', orderable: false }
                    ]
                });
            });

            // Global search across all tables
            $('#globalSearch').on('keyup', function() {
                const searchTerm = this.value.toLowerCase();
                $('.symbol-table tbody tr').each(function() {
                    const rowText = $(this).text().toLowerCase();
                    $(this).toggle(rowText.includes(searchTerm));
                });
            });
        });
    </script>
</body>
</html>
"""
    return html
