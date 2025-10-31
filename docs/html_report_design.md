# HTML Report Export Design Document

## 1. Overview

Design a new API endpoint to export Job violations as an interactive HTML report. The report provides a navigation-based interface with a sidebar for browsing violations and a main panel for viewing SQL file content with highlighted violations.

## 2. Requirements

### 2.1 Functional Requirements

1. **API Endpoint**: `GET /api/jobs/{job_id}/export/html`
   - Input: `job_id` (path parameter only)
   - File limit protection configured in backend `.env` (not in request parameter)

2. **Sidebar Navigation Layout**:
   - Left sidebar: File tree with violations, severity filter
   - Right panel: SQL file viewer (one file at a time)
   - Initial state: Right panel shows summary information

3. **Left Navigation Panel**:
   - Severity filter at top (multiple checkbox selection)
   - File tree showing:
     - Filename only (not full path)
     - Violation count per file
     - Violations listed as: `line_no: RULE_CODE` (e.g., "45: RF02")
     - Rule code background colored by severity
     - Violations sorted by line number within each file
     - Files sorted by filename
   - Collapsible/expandable file sections
   - Hover on rule code shows tooltip with:
     - Severity level
     - Rule code and name
     - Description
     - Line and column position

4. **Right Panel - SQL Viewer**:
   - Initial state: Show summary statistics (total violations, files, severity distribution)
   - After clicking violation: Display full SQL file content
   - File header showing full path and file stats
   - Line numbers for all SQL lines
   - No inline violation markers (clean SQL code)
   - Clicked violation line highlighted with severity-based background color
   - Smooth scroll to violation line on click
   - Active violation remains highlighted in left nav

5. **Interactive Features**:
   - Click violation in left nav → switch file + scroll to line + highlight
   - Severity filter dynamically shows/hides violations and files
   - Collapse/expand file sections in navigation
   - Active state tracking for selected violation

### 2.2 Non-Functional Requirements

1. **Performance**: Generate report within 5 seconds for configured file limit
2. **Single File Export**: Self-contained HTML with inline Tailwind CSS and JavaScript
3. **Browser Compatibility**: Modern browsers (Chrome, Firefox, Safari, Edge) with ES6+ support
4. **Print Support**: Print-friendly CSS for generating PDF reports
5. **Internationalization**: Chinese UI text throughout the interface
6. **API Usage**: Frontend server will request this API and render the HTML in browser

## 3. Data Flow

### 3.1 High-Level Process

```
┌─────────────────────────────────────────────────────────────┐
│  Client Request: GET /api/jobs/{job_id}/export/html         │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 1: Validate & Check File Limit                        │
│  - Validate job_id exists                                    │
│  - Count total tasks for this job                            │
│  - Check against EXPORT_HTML_FILE_LIMIT from .env           │
│  - If exceeded: Return JSON error response                   │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 2: Query Database                                      │
│  - Query linting_tasks: Get all tasks for job_id            │
│  - Query linting_violations: Get all violations (JOIN)       │
│  - Calculate summary statistics (severity distribution)      │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 3: Read SQL Files from NFS                            │
│  - Use source_file_path from linting_tasks                   │
│  - Read file content with multi-encoding support             │
│  - Handle missing/unreadable files gracefully (log warning)  │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 4: Combine Violations with SQL Context                │
│  - For each violation:                                       │
│    - Extract context (3 lines before/after violation line)   │
│    - Prepare tooltip data (severity, rule, description)      │
│  - Group violations by file and line proximity               │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 5: Generate HTML Report                                │
│  - Render using Jinja2 template                              │
│  - Inline CSS (Tailwind) and JavaScript                      │
│  - Return as HTMLResponse                                    │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 File Limit Protection

- File limit configured in `.env`:
  ```
  EXPORT_HTML_FILE_LIMIT=100  # Default: 100
  EXPORT_HTML_CONTEXT_LINES=3  # Default: 3
  ```

- If task count exceeds limit, return JSON error:
  ```json
  {
    "status": "limit_exceeded",
    "message": "文件数量超过限制",
    "job_id": "xxx",
    "total_files": 250,
    "limit": 100
  }
  ```

### 3.3 Logic Flow Suggestions

Your proposed logic is correct. Here are some refinements:

**✅ Good Points:**
- Query database first before reading files (efficient)
- Combine violations with SQL content
- Package into HTML

**💡 Suggested Improvements:**

1. **Add file count check BEFORE reading SQL files**
   - This prevents wasting time reading files if limit is exceeded

2. **Handle missing SQL files gracefully**
   - Some files may be deleted from NFS after task completion
   - Don't fail the entire report - just skip that file or show error message
   - Log warning and continue processing other files

3. **Use JOIN query for efficiency**
   - Single query to get tasks + violations (avoid N+1 problem)
   - Better performance than separate queries

4. **Consider caching for large jobs**
   - If same job is requested multiple times, consider caching the HTML
   - Or cache the SQL file reads (files rarely change after linting)

**Recommended Logic Flow:**
```
1. Validate job_id exists
2. Count tasks → check file limit
3. If OK: Query tasks + violations (single JOIN)
4. Read SQL files from NFS (parallel if possible)
5. Build report data structure
6. Render HTML template
7. Return HTML response
```

## 4. Database Query

### 4.1 Query Structure

**Task Count Query** (for limit check):
```sql
SELECT COUNT(*)
FROM linting_tasks
WHERE job_id = :job_id
```

**Main Data Query** (tasks + violations):
```sql
SELECT
    LintingTask.*,
    LintingViolation.*
FROM linting_tasks AS LintingTask
LEFT JOIN linting_violations AS LintingViolation
    ON LintingTask.task_id = LintingViolation.task_id
WHERE LintingTask.job_id = :job_id
ORDER BY
    LintingTask.source_file_path,
    LintingViolation.line_no
```

**Summary Statistics Query**:
```sql
SELECT
    severity_level,
    COUNT(*) as count
FROM linting_violations
WHERE job_id = :job_id
GROUP BY severity_level
```

## 5. Data Model

### 5.1 Report Data Structure

**ReportSummary**
- Job metadata (job_id, created_at)
- Total violations, total files
- Severity distribution (counts per severity level)
- Files with violations count

**FileTreeNode**
- File metadata (task_id, file_path, file_name)
- Total violations count
- List of violations (for navigation)
- SQL content (full file, list of lines with line numbers)
- Read error flag (if file couldn't be read)

**ViolationNavItem**
- Violation metadata (violation_id, task_id, rule_code, severity, line_no, column_no)
- Rule description (for tooltip)
- Rule name (for tooltip)
- Formatted tooltip content

**SQLFileData**
- task_id (identifier)
- Full file path
- File name
- Total lines
- SQL content as array of lines with line numbers
- Map of line_no → violations on that line
- Violation count

**NavigationData**
- List of FileTreeNode items (sorted by filename)
- Severity filter options
- Active filters (all checked by default)

### 5.2 Violation Display Strategy

**Navigation-Based Approach**:
- Left sidebar lists all violations in a file tree structure
- Rule codes displayed with severity-based background colors
- Right panel shows clean SQL code (no inline markers)
- Color coding by severity:
  - CRITICAL: `bg-red-600`
  - BLOCKER: `bg-orange-600`
  - MAJOR: `bg-yellow-600`
  - MINOR: `bg-blue-600`
  - INFO: `bg-gray-600`

**Interaction Flow**:
1. User clicks violation in left nav (e.g., "45: RF02")
2. Right panel switches to that SQL file (if different file)
3. Violation line highlighted with severity-colored background
4. Page smoothly scrolls to bring violation line into view
5. Active violation in left nav shows active state

**Visual Example - Left Navigation**:
```
┌─ 过滤器 ─────────────────┐
│ ☑ CRITICAL  ☑ BLOCKER   │
│ ☑ MAJOR     ☑ MINOR     │
│ ☑ INFO                  │
└──────────────────────────┘

📁 file1.sql (5)
  ├─ 45: RF02  [🟡 MAJOR bg]
  ├─ 89: LT01  [🔴 CRITICAL bg]
  └─ 102: RF02 [🟡 MAJOR bg]

📁 file2.sql (3)
  ├─ 12: ST03  [🟡 MAJOR bg]
  └─ 34: CP01  [🔵 MINOR bg]
```

Hover on rule code (e.g., `RF02`) shows tooltip:
```
┌─────────────────────────────────────┐
│ 🟡 MAJOR                            │
│ RF02 - references.qualification     │
│ 未限定的引用 'product5'              │
│ 位置: 第45行:12列                    │
└─────────────────────────────────────┘
```

**Visual Example - Right Panel (Initial State)**:
```
┌────────────────────────────────────────┐
│  📊 SQL核验报告汇总                     │
│                                        │
│  总文件数: 15                           │
│  总违规项: 42                           │
│  存在问题的文件: 8                      │
│                                        │
│  严重级别分布:                          │
│  🔴 CRITICAL: 5                        │
│  🟠 BLOCKER: 8                         │
│  🟡 MAJOR: 15                          │
│  🔵 MINOR: 10                          │
│  ⚪ INFO: 4                            │
│                                        │
│  ← 点击左侧违规项查看详细SQL代码        │
└────────────────────────────────────────┘
```

**Visual Example - Right Panel (After Click)**:
```
┌────────────────────────────────────────┐
│ 📄 /data/sql/project/file1.sql        │
│ 150 lines | 5 violations              │
└────────────────────────────────────────┘

  42: SELECT *
  43: FROM products
  44: WHERE 1=1
▶45: SELECT product5.name    ← Highlighted (yellow bg)
  46: FROM category
  47: ;
```

## 6. HTML Layout Design

### 6.1 Overall Structure

The HTML report uses a **two-column layout** with sidebar navigation:

```
┌─────────────────────────────────────────────────────────┐
│  Header: SQL核验报告 | Job ID | Generated Time          │
└─────────────────────────────────────────────────────────┘
┌──────────────────┬──────────────────────────────────────┐
│  Left Sidebar    │  Right Panel                         │
│  (300px fixed)   │  (Flexible width)                    │
│                  │                                      │
│  ┌────────────┐  │  ┌────────────────────────────────┐ │
│  │  Filter    │  │  │  Initial: Summary Info         │ │
│  └────────────┘  │  │  or                            │ │
│                  │  │  Clicked: SQL File Content     │ │
│  📁 Files        │  └────────────────────────────────┘ │
│   ├─ Violations │                                      │
│   ...            │                                      │
│                  │                                      │
└──────────────────┴──────────────────────────────────────┘
```

**Layout Components**:

1. **Header Bar** (full width, top):
   - Report title: "SQL核验报告"
   - Job ID and generation timestamp

2. **Left Sidebar** (fixed 300px width, scrollable):
   - Severity filter (checkboxes)
   - File tree with violations
   - Collapsible file sections
   - Violation items with line number and rule code

3. **Right Panel** (flexible width, main content):
   - **Initial state**: Summary statistics
   - **After click**: SQL file viewer with highlighted violation line

### 6.2 HTML Fragment Version (Main API)

Returns HTML fragment (no `<html>`, `<head>`, `<body>` wrapper) for Vue3 frontend integration.

**Structure**:
```html
<div class="sql-report" id="sql-report-{job_id}">
    <!-- Header -->
    <header class="report-header">
        <h1>SQL核验报告</h1>
        <div>工作ID: {job_id} | 生成时间: {created_at}</div>
    </header>

    <!-- Main Layout: Sidebar + Content -->
    <div class="report-layout">

        <!-- Left Sidebar -->
        <aside class="sidebar">
            <!-- Severity Filter -->
            <div class="filter-section">
                <h3>过滤器</h3>
                <div class="filter-checkboxes">
                    <label><input type="checkbox" value="CRITICAL" checked> CRITICAL</label>
                    <label><input type="checkbox" value="BLOCKER" checked> BLOCKER</label>
                    <label><input type="checkbox" value="MAJOR" checked> MAJOR</label>
                    <label><input type="checkbox" value="MINOR" checked> MINOR</label>
                    <label><input type="checkbox" value="INFO" checked> INFO</label>
                </div>
            </div>

            <!-- File Tree Navigation -->
            <nav class="file-tree">
                <!-- File Section (repeated for each file) -->
                <div class="file-item" data-task-id="{task_id}">
                    <!-- File Header (collapsible) -->
                    <div class="file-header" onclick="toggleFileSection(this)">
                        <span class="toggle-icon">▼</span>
                        <span class="file-icon">📁</span>
                        <span class="file-name">{filename}</span>
                        <span class="violation-count">({violation_count})</span>
                    </div>

                    <!-- Violations List -->
                    <ul class="violations-list">
                        <!-- Violation Item -->
                        <li class="violation-item"
                            data-task-id="{task_id}"
                            data-line="{line_no}"
                            data-severity="{severity}"
                            onclick="showViolation(this)">
                            <span class="line-number">{line_no}:</span>
                            <span class="rule-code severity-{severity}"
                                  data-tooltip="tooltip-{violation_id}">
                                {rule_code}
                            </span>
                            <!-- Tooltip (shown on hover) -->
                            <div class="tooltip hidden" id="tooltip-{violation_id}">
                                <div class="severity-badge severity-{severity}">{severity}</div>
                                <div class="rule-name">{rule_code} - {rule_name}</div>
                                <div class="description">{description}</div>
                                <div class="position">位置: 第{line_no}行:{column_no}列</div>
                            </div>
                        </li>
                        <!-- More violations... -->
                    </ul>
                </div>
                <!-- More files... -->
            </nav>
        </aside>

        <!-- Right Panel -->
        <main class="content-panel">
            <!-- Initial State: Summary View -->
            <div id="summary-view" class="summary-view">
                <h2>📊 SQL核验报告汇总</h2>
                <div class="stats-grid">
                    <div class="stat-card">
                        <div class="stat-label">总文件数</div>
                        <div class="stat-value">{total_files}</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">总违规项</div>
                        <div class="stat-value">{total_violations}</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">存在问题的文件</div>
                        <div class="stat-value">{files_with_violations}</div>
                    </div>
                </div>

                <!-- Severity Distribution -->
                <div class="severity-distribution">
                    <h3>严重级别分布</h3>
                    <div class="severity-bars">
                        <div class="severity-bar">
                            <span class="severity-label">🔴 CRITICAL</span>
                            <span class="severity-count">{critical_count}</span>
                        </div>
                        <!-- More severity levels... -->
                    </div>
                </div>

                <p class="hint">← 点击左侧违规项查看详细SQL代码</p>
            </div>

            <!-- SQL File View (hidden initially, shown on click) -->
            <div id="sql-view" class="sql-view hidden" data-current-task-id="">
                <!-- File Header -->
                <div class="file-info">
                    <h3 class="file-path">{full_file_path}</h3>
                    <div class="file-stats">{total_lines} 行 | {violation_count} 个违规项</div>
                </div>

                <!-- SQL Code Block -->
                <div class="code-container">
                    <pre class="code-block"><code><!-- SQL Lines (generated dynamically) -->
<span class="code-line" data-line="1">  1: SELECT * FROM users</span>
<span class="code-line" data-line="2">  2: WHERE status = 1</span>
<!-- ... -->
<span class="code-line violation-line" data-line="45" data-severity="MAJOR"> 45: SELECT product5.name</span>
<!-- ... -->
</code></pre>
                </div>
            </div>
        </main>

    </div>

    <!-- JavaScript for interactivity -->
    <script>
        // Violation click handler
        // Severity filtering
        // Tooltip show/hide
        // File section collapse/expand
        // Smooth scroll and highlighting
    </script>
</div>
```

### 6.3 Standalone HTML Version (Development API)

For development/testing: `GET /api/jobs/{job_id}/export/html/standalone`

Returns complete HTML document with:
- Full HTML structure (`<html>`, `<head>`, `<body>`)
- Tailwind CSS CDN link
- Print styles
- Same content as fragment version

**Use cases**:
- Open in new browser tab for preview
- CSS development and testing
- Download as standalone HTML file

## 7. JavaScript Functionality

### 7.1 Core Features

**Violation Click Handler** (`showViolation(element)`):
- Get target task_id, line_no, and severity from clicked element
- Switch to SQL view if in summary view
- Load SQL file content if different file (AJAX or pre-loaded in data)
- Highlight violation line with severity-based background color
- Smooth scroll to bring line into viewport
- Set active state on clicked violation item in left nav
- Remove previous active states

**Severity Filtering**:
- Checkbox-based multi-select filter in sidebar
- Show/hide violation items based on selected severities
- Hide file sections if all violations are filtered out
- Dynamically update violation counts in file headers
- Maintain filter state during navigation

**Tooltip Display**:
- Show tooltip on hover over rule code in left nav
- Position tooltip near cursor (or adjacent to element)
- Hide tooltip on mouse leave
- Handle multiple tooltips on same page
- Ensure tooltip doesn't overflow viewport

**File Section Collapse/Expand** (`toggleFileSection(element)`):
- Toggle visibility of violations list under file
- Rotate toggle icon (▼ ↔ ▶)
- Smooth animation for collapse/expand
- Remember collapsed state during session

**Smooth Scrolling and Highlighting**:
- Use `scrollIntoView({ behavior: 'smooth', block: 'center' })` to scroll to line
- Apply highlight class to target line with fade-in animation
- Optional: Remove highlight after a few seconds (or keep until next click)

**Print Support**:
- Hide left sidebar when printing
- Show full SQL file content
- Expand all tooltips inline (no hover required)
- Ensure violation lines are clearly marked

## 8. API Endpoint Design

### 8.1 Main Endpoint (Production)

```
GET /api/jobs/{job_id}/export/html
```

**Response**:
- Success (200): HTML fragment (text/html)
- Limit exceeded (200): JSON with error details
- Not found (404): JSON with error message
- Server error (500): JSON with error message

### 8.2 Standalone Endpoint (Development)

```
GET /api/jobs/{job_id}/export/html/standalone
```

**Response**:
- Same as main endpoint, but returns full HTML document with Tailwind CDN

## 9. Implementation Considerations

### 9.1 SQL File Reading

- **Multi-encoding support**: Try UTF-8, GBK, GB18030, Latin1
- **Graceful error handling**: If file missing/unreadable, show error message in report
- **Parallel reading**: Read multiple files concurrently for better performance

### 9.2 Context Extraction

- **Smart grouping**: Merge violations within 6 lines into single context block
- **Edge cases**: Handle violations at file start/end (< 3 lines available)
- **Multiple violations per line**: Show all violations in single tooltip

### 9.3 HTML Rendering

- **Use Jinja2 template engine** for clean separation of logic and presentation
- **Auto-escape**: Prevent XSS by escaping all user content (SQL code, descriptions)
- **Minify**: Remove unnecessary whitespace in production

### 9.4 Performance Optimization

- **Single JOIN query**: Avoid N+1 problem
- **Async file reading**: Use async I/O for NFS reads
- **Lazy rendering**: Consider pagination for very large reports (future enhancement)

## 10. Configuration

Add to `.env` or `app/config/settings.py`:

```python
# HTML Report Export Configuration
EXPORT_HTML_FILE_LIMIT=100        # Maximum files per export
EXPORT_HTML_CONTEXT_LINES=3       # Lines before/after violation
```

## 11. File Organization

```
app/
├── api/
│   └── routes/
│       └── jobs.py
│           - GET /jobs/{job_id}/export/html
│           - GET /jobs/{job_id}/export/html/standalone
│
├── services/
│   └── report_service.py (NEW)
│       - HtmlReportService class
│       - generate_report_data()
│       - render_html_fragment()
│       - render_html_standalone()
│
├── templates/
│   ├── html_report_fragment.jinja2 (NEW)
│   └── html_report_standalone.jinja2 (NEW)
│
└── utils/
    └── file_reader.py (NEW)
        - read_sql_file_with_encoding()
        - Multi-encoding support
```

## 12. Styling (Tailwind CSS)

### 12.1 Layout Styles

**Main Layout**:
- `.report-layout`: `display: flex; height: calc(100vh - header-height);`
- `.sidebar`: `width: 300px; overflow-y: auto; border-right: 1px solid gray-200; background: white;`
- `.content-panel`: `flex: 1; overflow-y: auto; padding: 20px; background: gray-50;`

**Sidebar Styles**:
- `.file-tree`: Nested list structure with indentation
- `.file-header`: Clickable, cursor pointer, hover background
- `.violation-item`: Padding, hover effect, cursor pointer
- `.rule-code`: Inline badge with severity-colored background, rounded corners
- Active state: Background highlight for selected violation

### 12.2 Color Scheme

**Severity Colors (Rule Code Badges)**:
- CRITICAL: `bg-red-600 text-white`
- BLOCKER: `bg-orange-600 text-white`
- MAJOR: `bg-yellow-600 text-white`
- MINOR: `bg-blue-600 text-white`
- INFO: `bg-gray-600 text-white`

**Severity Colors (Violation Line Highlight)**:
- CRITICAL: `bg-red-100 border-l-4 border-red-600`
- BLOCKER: `bg-orange-100 border-l-4 border-orange-600`
- MAJOR: `bg-yellow-100 border-l-4 border-yellow-600`
- MINOR: `bg-blue-100 border-l-4 border-blue-600`
- INFO: `bg-gray-100 border-l-4 border-gray-600`

**Layout Colors**:
- Page background: `bg-gray-100`
- Sidebar background: `bg-white`
- Content panel background: `bg-gray-50`
- Borders: `border-gray-200`
- Code background: `bg-gray-900`
- Code text: `text-gray-300` (normal), `text-white` (highlighted)

**Interactive States**:
- Hover: Lighten background slightly
- Active violation: `bg-blue-50` in left nav
- Collapsed file: Rotate icon, hide list

### 12.3 Print Styles

```css
@media print {
    .sidebar { display: none !important; }  /* Hide left navigation */
    .content-panel { width: 100% !important; }  /* Full width for content */
    .tooltip { display: block !important; position: static !important; }  /* Show tooltips inline */
    .violation-line { border-left: 4px solid !important; }  /* Ensure borders are visible */
    .code-container { page-break-inside: avoid; }  /* Avoid breaking code blocks */
}
```

## 13. Security Considerations

1. **XSS Prevention**: HTML-escape all SQL code and violation descriptions
2. **Path Traversal**: Validate file paths are within NFS root directory
3. **DoS Prevention**: Enforce file limit (configurable in .env)
4. **SQL Injection**: Use parameterized queries for all database operations

## 14. Testing Strategy

**Unit Tests**:
- SQL context extraction (edge cases: start/end of file, invalid line numbers)
- File encoding detection
- Violation grouping by proximity

**Integration Tests**:
- API endpoint with small dataset (< limit)
- API endpoint with large dataset (> limit)
- Missing SQL files handling
- Non-existent job_id

**UI Tests**:
- Severity filtering functionality
- Tooltip display on hover
- SQL expansion toggle
- Print layout

---

## Summary

This design focuses on:

1. **✅ Sidebar navigation layout** - File tree with violations on left, SQL viewer on right
2. **✅ Clean SQL code display** - No inline markers, highlight violations on click
3. **✅ File limit in .env** - `EXPORT_HTML_FILE_LIMIT=100`
4. **✅ Clear logic flow**:
   - Query database (linting_tasks + linting_violations)
   - Read SQL files from NFS
   - Build file tree structure with violations
   - Render HTML template with initial summary view
5. **✅ Interactive navigation**:
   - Click violation → jump to line in SQL file
   - Severity filtering in sidebar
   - Collapsible file sections
   - Tooltip on hover for violation details
6. **✅ Initial state** - Summary statistics displayed in right panel
7. **✅ Single file view** - One SQL file displayed at a time
8. **✅ Line numbers in navigation** - Format: `line_no: RULE_CODE`

**Key Features**:
- Navigation-first design for easy browsing
- Focused, distraction-free SQL code view
- Severity-based color coding throughout
- Smooth scrolling and highlighting
- Print-friendly layout

**Document Version**: 5.0 (Navigation Layout)
**Last Updated**: 2025-10-28
**Author**: Claude Code Assistant
