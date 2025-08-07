# LaTeX Compiler Service

A robust FastAPI-based web service for compiling LaTeX documents to PDF. This service supports both single file compilation and complex project structures with automatic compiler detection and bibliography processing.

## Features

- **Multiple Compilation Modes**

  - Single `.tex` file compilation
  - Complex project structure compilation with folder hierarchy
  - Automatic compiler detection (pdflatex, xelatex, lualatex)

- **Smart Processing**

  - Automatic bibliography processing (bibtex/biber)
  - Multi-pass compilation for cross-references
  - Unicode support detection
  - Font package detection

- **Security & Validation**

  - Input sanitization and validation
  - Path traversal protection
  - Dangerous command detection
  - File extension validation

- **Comprehensive File Support**
  - LaTeX files: `.tex`, `.cls`, `.sty`, `.bib`, `.bst`
  - Images: `.pdf`, `.png`, `.jpg`, `.jpeg`, `.gif`, `.eps`, `.svg`
  - Data files: `.txt`, `.dat`, `.csv`
  - Scripts: `.lua`, `.py`, `.r`

## Installation

### Using Docker (Recommended)

1. **Build the Docker image:**

   ```bash
   docker build -t latex-compiler .
   ```

2. **Run the container:**
   ```bash
   docker run -p 8000:8000 latex-compiler
   ```

### Local Installation

1. **Install system dependencies (Ubuntu/Debian):**

   ```bash
   sudo apt-get update && sudo apt-get install -y \
       texlive-latex-base \
       texlive-latex-recommended \
       texlive-latex-extra \
       texlive-fonts-recommended \
       texlive-fonts-extra \
       texlive-science \
       texlive-bibtex-extra \
       texlive-xetex \
       texlive-lang-all \
       poppler-utils \
       python3 \
       python3-pip
   ```

2. **Install Python dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

3. **Run the service:**
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8000
   ```

## API Documentation

Once the service is running, visit `http://localhost:8000/docs` for interactive API documentation.

### Endpoints

#### `POST /compile-single`

Compile a single LaTeX file to PDF.

**Request:** Upload a `.tex` file
**Response:** PDF file or error details

**Example:**

```bash
curl -X POST "http://localhost:8000/compile-single" \
     -H "Content-Type: multipart/form-data" \
     -F "file=@document.tex" \
     --output document.pdf
```

#### `POST /compile-project`

Compile a LaTeX project from structured folder data.

**Request Body:**

```json
{
  "project_data": {
    "id": "project-id",
    "name": "My Project",
    "is_root": true,
    "files": [
      {
        "id": "main-tex",
        "folder_id": "root",
        "name": "main.tex",
        "format": "tex",
        "content": "\\documentclass{article}...",
        "url": ""
      }
    ],
    "subfolders": []
  },
  "main_file": "main.tex"
}
```

**Response:** PDF file or error details

#### `GET /info`

Get service information and supported file types.

#### `GET /compilers`

List available LaTeX compilers on the system.

#### `GET /`

Health check endpoint.

## Project Structure Format

The service accepts projects in a hierarchical JSON format:

```json
{
  "project_data": {
    "id": "unique-id",
    "name": "Project Name",
    "is_root": true,
    "files": [
      {
        "id": "file-id",
        "folder_id": "parent-folder-id",
        "name": "filename.tex",
        "format": "tex",
        "content": "file content here",
        "url": "optional-download-url",
        "projectId": "optional-project-id"
      }
    ],
    "subfolders": [
      {
        "id": "subfolder-id",
        "name": "images",
        "is_root": false,
        "files": [...],
        "subfolders": [...]
      }
    ]
  },
  "main_file": "main.tex"
}
```

## Compiler Selection

The service automatically selects the appropriate LaTeX compiler based on:

1. **XeLaTeX** for documents using:

   - `fontspec`, `xltxtra`, `xunicode`, `polyglossia` packages
   - `\setmainfont`, `\setsansfont`, `\setmonofont` commands
   - Non-ASCII characters

2. **LuaLaTeX** for documents using:

   - `luacode`, `luatextra`, `luamplib` packages

3. **PDFLaTeX** (default) for standard documents

## Bibliography Processing

The service automatically detects and processes bibliographies:

- Checks for `.bib` files in the project
- Runs `biber` first (for biblatex), then falls back to `bibtex`
- Performs additional compilation passes as needed

## Security Features

- **Path validation:** Prevents directory traversal attacks
- **Command filtering:** Blocks dangerous LaTeX commands like `\write18`
- **File extension validation:** Only allows safe file types
- **Content sanitization:** Validates LaTeX source before compilation

## Error Handling

The service provides detailed error responses:

```json
{
  "error": "LaTeX compilation failed",
  "compiler": "pdflatex",
  "log": "detailed compilation log..."
}
```

Common HTTP status codes:

- `200`: Successful compilation
- `400`: Invalid input (bad file type, missing main file)
- `408`: Compilation timeout
- `422`: LaTeX compilation errors
- `500`: Internal server error

## Development

### Requirements

- Python 3.8+
- FastAPI
- uvicorn
- requests
- Complete LaTeX distribution (TeX Live recommended)

### Running in Development Mode

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Testing

Test the service with a simple LaTeX document:

```latex
\documentclass{article}
\begin{document}
Hello, World!
\end{document}
```

Save as `test.tex` and upload via the `/compile-single` endpoint.

## Configuration

The service can be configured through environment variables:

- `PORT`: Service port (default: 8000)
- `HOST`: Service host (default: 0.0.0.0)

## Limitations

- Compilation timeout: 120 seconds per pass
- Bibliography processing timeout: 30 seconds
- No external network access during compilation
- File size limits depend on available memory

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is open source. Please check the license file for details.

## Support

For issues and questions:

1. Check the API documentation at `/docs`
2. Review the service info at `/info`
3. Check logs for detailed error information
4. Ensure all required LaTeX packages are installed

## Architecture

The service is built with:

- **FastAPI**: Modern, fast web framework for building APIs
- **Docker**: Containerization for easy deployment
- **TeX Live**: Comprehensive LaTeX distribution
- **Subprocess management**: Secure compilation execution
- **Temporary directories**: Isolated compilation environments

Each compilation runs in an isolated temporary directory with proper cleanup, ensuring security and preventing interference between requests.
