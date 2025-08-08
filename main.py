import subprocess
import tempfile
import os
from pathlib import Path
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.responses import Response
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import logging

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://www.researchcommons.ai","https://okinresearch.com", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Supported file extensions for LaTeX projects
ALLOWED_EXTENSIONS = {
    '.tex', '.cls', '.sty', '.bib', '.bst',  # LaTeX files
    '.pdf', '.png', '.jpg', '.jpeg', '.gif', '.eps', '.svg',  # Images
    '.txt', '.dat', '.csv',  # Data files
    '.lua', '.py', '.r',  # Script files (for dynamic content)
}

class FileInfo(BaseModel):
    id: str
    folder_id: str
    name: str
    format: str  # File format (tex, pdf, etc.)
    content: str
    projectId: Optional[str] = None
    ownerId: Optional[str] = None
    created_at: str
    updated_at: str

class PaperFolderData(BaseModel):
    id: str
    name: str
    type: str
    tag: str
    user_id: str
    created_at: str
    updated_at: str
    user: Optional[Any] = None
    files: List[FileInfo]
    is_root: bool
    depth: int
    subfolders: List['PaperFolderData'] = []

class CompileRequest(BaseModel):
    project_data: PaperFolderData
    main_file: Optional[str] = None  # Optional main file name

def is_safe_path(path: str) -> bool:
    """
    Check if a file path is safe (no directory traversal attacks).
    
    Args:
        path: File path to validate
        
    Returns:
        True if path is safe, False otherwise
    """
    # Normalize the path
    normalized = os.path.normpath(path)
    
    # Check for directory traversal attempts
    if normalized.startswith('..') or '/../' in normalized or normalized.startswith('/'):
        return False
    
    return True

def create_project_structure(folder_data: PaperFolderData, base_path: Path, current_path: Path = None) -> Dict[str, Path]:
    """
    Recursively create the project folder structure and files.
    
    Args:
        folder_data: The folder data structure
        base_path: Base directory path
        current_path: Current directory path (for recursion)
        
    Returns:
        Dictionary mapping file IDs to their paths
    """
    if current_path is None:
        current_path = base_path
    
    file_paths = {}
    
    # Create current folder if not root
    if not folder_data.is_root:
        folder_path = current_path / folder_data.name
        folder_path.mkdir(exist_ok=True)
        current_path = folder_path
    
    # Create files in current folder
    for file_info in folder_data.files:
        if not is_safe_path(file_info.name):
            logger.warning(f"Skipping unsafe file path: {file_info.name}")
            continue
        
        file_path = current_path / file_info.name
        
        # Validate file extension
        file_ext = Path(file_info.name).suffix.lower()
        if file_ext and file_ext not in ALLOWED_EXTENSIONS:
            logger.warning(f"Skipping file with unsupported extension: {file_info.name}")
            continue
        
        try:
            # Handle binary files (encoded as base64) vs text files
            if file_info.format.lower() in ['png', 'jpg', 'jpeg', 'gif', 'pdf', 'eps']:
                # Binary files - assume content is base64 encoded
                import base64
                try:
                    binary_content = base64.b64decode(file_info.content)
                    with open(file_path, 'wb') as f:
                        f.write(binary_content)
                except Exception as e:
                    logger.error(f"Error writing binary file {file_info.name}: {e}")
                    continue
            else:
                # Text files
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(file_info.content)
            
            file_paths[file_info.id] = file_path
            logger.info(f"Created file: {file_path}")
            
        except Exception as e:
            logger.error(f"Error creating file {file_info.name}: {e}")
            continue
    
    # Recursively create subfolders
    for subfolder in folder_data.subfolders:
        subfolder_paths = create_project_structure(subfolder, base_path, current_path)
        file_paths.update(subfolder_paths)
    
    return file_paths

def find_main_tex_file(folder_data: PaperFolderData, file_paths: Dict[str, Path], specified_main: Optional[str] = None) -> Optional[Path]:
    """
    Find the main .tex file in the project.
    
    Args:
        folder_data: The project folder structure
        file_paths: Dictionary of file ID to path mappings
        specified_main: Optional specified main file name
        
    Returns:
        Path to the main .tex file or None if not found
    """
    tex_files = []
    
    # Collect all .tex files recursively
    def collect_tex_files(folder: PaperFolderData):
        for file_info in folder.files:
            if file_info.format.lower() == 'tex':
                if file_info.id in file_paths:
                    tex_files.append((file_info, file_paths[file_info.id]))
        
        for subfolder in folder.subfolders:
            collect_tex_files(subfolder)
    
    collect_tex_files(folder_data)
    
    if not tex_files:
        return None
    
    # If main file is specified, try to find it
    if specified_main:
        for file_info, file_path in tex_files:
            if file_info.name == specified_main:
                return file_path
        logger.warning(f"Specified main file {specified_main} not found")
    
    # Look for common main file names
    common_names = ['main.tex', 'document.tex', 'paper.tex', 'thesis.tex']
    for common_name in common_names:
        for file_info, file_path in tex_files:
            if file_info.name.lower() == common_name.lower():
                return file_path
    
    # Look for files with \documentclass
    for file_info, file_path in tex_files:
        try:
            if '\\documentclass' in file_info.content[:1000]:  # Check first 1000 chars
                return file_path
        except Exception:
            continue
    
    # Fall back to first .tex file
    return tex_files[0][1] if tex_files else None

def choose_compiler(tex_source: str) -> str:
    """
    Choose the appropriate LaTeX compiler based on the document content.
    
    Args:
        tex_source: The LaTeX source code as a string
        
    Returns:
        The compiler command name ('xelatex', 'lualatex', or 'pdflatex')
    """
    # Check for XeLaTeX-specific packages
    xelatex_packages = ['fontspec', 'xltxtra', 'xunicode', 'polyglossia']
    if any(f'\\usepackage{{{pkg}}}' in tex_source for pkg in xelatex_packages):
        return 'xelatex'
    
    # Check for LuaLaTeX-specific packages
    lualatex_packages = ['luacode', 'luatextra', 'luamplib']
    if any(f'\\usepackage{{{pkg}}}' in tex_source for pkg in lualatex_packages):
        return 'lualatex'
    
    # Check for non-ASCII characters (suggests need for Unicode support)
    if any(ord(c) > 127 for c in tex_source):
        return 'xelatex'
    
    # Check for specific font commands
    if '\\setmainfont' in tex_source or '\\setsansfont' in tex_source or '\\setmonofont' in tex_source:
        return 'xelatex'
    
    # Default to pdflatex for standard documents
    return 'pdflatex'

def validate_tex_file(tex_source: str) -> None:
    """
    Basic validation of LaTeX source for security and sanity.
    
    Args:
        tex_source: The LaTeX source code to validate
        
    Raises:
        HTTPException: If validation fails
    """
    # Check for potentially dangerous commands
    dangerous_commands = [
        '\\write18',  # Shell escape
        '\\immediate\\write18',  # Shell escape
        '\\input{|',  # Pipe input
        '\\openin',   # File operations
        '\\openout',  # File operations
    ]
    
    for cmd in dangerous_commands:
        if cmd in tex_source:
            raise HTTPException(
                status_code=400, 
                detail=f"Potentially dangerous command detected: {cmd}"
            )

def run_bibtex_if_needed(project_dir: Path, main_tex_name: str, compiler: str) -> tuple[bool, str]:
    """
    Run bibtex/biber if bibliography files are present.
    
    Args:
        project_dir: Project directory
        main_tex_name: Name of main tex file (without extension)
        compiler: LaTeX compiler being used
        
    Returns:
        Tuple of (success: bool, logs: str)
    """
    bib_logs = ""
    
    # Check if there are .bib files
    bib_files = list(project_dir.rglob('*.bib'))
    if not bib_files:
        return False, "No .bib files found"
    
    # Check if .aux file exists and contains bibliography citations
    aux_file = project_dir / f"{main_tex_name}.aux"
    if not aux_file.exists():
        return False, "No .aux file found"
    
    try:
        with open(aux_file, 'r', encoding='utf-8', errors='ignore') as f:
            aux_content = f.read()
            if '\\bibdata' not in aux_content and '\\citation' not in aux_content:
                return False, "No bibliography citations found in .aux file"
    except Exception as e:
        return False, f"Error reading .aux file: {str(e)}"
    
    # Try biber first (for biblatex), then bibtex
    for bib_processor in ['biber', 'bibtex']:
        try:
            logger.info(f"Running {bib_processor}")
            proc = subprocess.run(
                [bib_processor, main_tex_name],
                cwd=project_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30
            )
            
            bib_logs += f"=== {bib_processor.upper()} ===\n"
            bib_logs += f"Return code: {proc.returncode}\n"
            bib_logs += f"STDOUT:\n{proc.stdout}\n"
            bib_logs += f"STDERR:\n{proc.stderr}\n\n"
            
            if proc.returncode == 0:
                logger.info(f"{bib_processor} completed successfully")
                return True, bib_logs
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            bib_logs += f"Failed to run {bib_processor}: {str(e)}\n"
            continue
    
    logger.warning("Could not run bibliography processor")
    return False, bib_logs

@app.post("/compile-single")
async def compile_single_file(file: UploadFile = File(...)):
    """
    Compile a single LaTeX file to PDF with detailed logs.
    
    Args:
        file: Uploaded .tex file
        
    Returns:
        JSON response with compilation status, PDF data (hex if successful), and logs
    """
    # Validate file type
    if not file.filename.endswith('.tex'):
        raise HTTPException(status_code=400, detail="File must have .tex extension")
    
    try:
        # Read and decode the file
        tex_source = await file.read()
        tex_str = tex_source.decode('utf-8', errors='ignore')
        
        # Validate the LaTeX source
        validate_tex_file(tex_str)
        
        # Choose appropriate compiler
        compiler = choose_compiler(tex_str)
        logger.info(f"Using compiler: {compiler}")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            tex_path = project_dir / "main.tex"
            
            # Write the LaTeX source to file
            with open(tex_path, 'w', encoding='utf-8') as f:
                f.write(tex_str)
            
            # Compile the document
            success, logs = await compile_project(project_dir, tex_path, compiler)
            
            if not success:
                return {
                    "status": "error",
                    "message": "LaTeX compilation failed",
                    "error": "LaTeX compilation failed",
                    "compiler": compiler,
                    "logs": logs,
                    "filename": file.filename
                }
            
            # Read and return the PDF with logs
            pdf_path = project_dir / "main.pdf"
            with open(pdf_path, 'rb') as pdf_file:
                pdf_data = pdf_file.read()
            
            return {
                "status": "success",
                "message": "LaTeX compilation successful",
                "compiler": compiler,
                "pdf_data": pdf_data.hex(),
                "logs": logs,
                "filename": file.filename.replace('.tex', '.pdf')
            }
    
    except Exception as e:
        logger.error(f"Compilation error: {str(e)}")
        if isinstance(e, HTTPException):
            raise
        return {
            "status": "error",
            "message": "Internal server error",
            "error": f"Internal server error: {str(e)}",
            "logs": "",
            "filename": file.filename if file.filename else "unknown"
        }

@app.post("/compile-single-download")
async def compile_single_file_download(file: UploadFile = File(...)):
    """
    Compile a single LaTeX file to PDF and return as file download.
    
    Args:
        file: Uploaded .tex file
        
    Returns:
        PDF file as direct download
    """
    # Get the detailed response
    detailed_response = await compile_single_file(file)
    
    if detailed_response["status"] == "success":
        # Convert hex back to binary
        pdf_data = bytes.fromhex(detailed_response["pdf_data"])
        
        return Response(
            content=pdf_data,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename={detailed_response['filename']}",
                "X-Compilation-Logs": "See /compile-single for detailed logs"
            }
        )
    else:
        raise HTTPException(status_code=422, detail=detailed_response)

@app.post("/compile-project")
async def compile_latex_project(request: CompileRequest):
    """
    Compile a LaTeX project from structured folder data to PDF.
    
    Args:
        request: CompileRequest containing project_data and optional main_file
        
    Returns:
        JSON response with compilation status, PDF data (hex if successful), and logs
    """
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            
            # Create project structure and files
            logger.info("Creating project structure")
            file_paths = create_project_structure(request.project_data, project_dir)
            
            if not file_paths:
                raise HTTPException(status_code=400, detail="No valid files found in project")
            
            # Find main .tex file
            main_tex_path = find_main_tex_file(request.project_data, file_paths, request.main_file)
            
            if not main_tex_path:
                raise HTTPException(status_code=400, detail="No main .tex file found in project")
            
            logger.info(f"Using main file: {main_tex_path}")
            
            # Read main tex file to determine compiler
            with open(main_tex_path, 'r', encoding='utf-8', errors='ignore') as f:
                tex_content = f.read()
            
            # Validate the LaTeX source
            validate_tex_file(tex_content)
            
            # Choose appropriate compiler
            compiler = choose_compiler(tex_content)
            logger.info(f"Using compiler: {compiler} for project")
            
            # Compile the project
            success, logs = await compile_project(project_dir, main_tex_path, compiler)
            
            if not success:
                return {
                    "status": "error",
                    "message": "LaTeX project compilation failed",
                    "error": "LaTeX project compilation failed",
                    "compiler": compiler,
                    "logs": logs,
                    "main_file": main_tex_path.name,
                    "project_name": request.project_data.name
                }
            
            # Read and return the PDF
            pdf_name = main_tex_path.stem + ".pdf"
            pdf_path = main_tex_path.parent / pdf_name
            
            if not pdf_path.exists():
                return {
                    "status": "error",
                    "message": "PDF was not generated",
                    "error": "PDF was not generated despite successful compilation",
                    "compiler": compiler,
                    "logs": logs,
                    "main_file": main_tex_path.name,
                    "project_name": request.project_data.name
                }
            
            with open(pdf_path, 'rb') as pdf_file:
                pdf_data = pdf_file.read()
            
            logger.info("LaTeX project compilation successful")
            return {
                "status": "success",
                "message": "LaTeX compilation successful",
                "compiler": compiler,
                "pdf_data": pdf_data.hex(),
                "logs": logs,
                "main_file": main_tex_path.name,
                "project_name": request.project_data.name
            }
    
    except Exception as e:
        logger.error(f"Project compilation error: {str(e)}")
        if isinstance(e, HTTPException):
            raise
        return {
            "status": "error",
            "message": "Internal server error",
            "error": f"Internal server error: {str(e)}",
            "logs": "",
            "project_name": getattr(request.project_data, 'name', 'unknown') if hasattr(request, 'project_data') else 'unknown'
        }

async def compile_project(project_dir: Path, main_tex_path: Path, compiler: str) -> tuple[bool, str]:
    """
    Compile a LaTeX project with proper handling of bibliography and multiple runs.
    
    Args:
        project_dir: Directory containing the project
        main_tex_path: Path to the main .tex file
        compiler: LaTeX compiler to use
        
    Returns:
        Tuple of (success: bool, logs: str)
    """
    main_tex_name = main_tex_path.stem
    working_dir = main_tex_path.parent
    all_logs = ""
    first_pass_logs = ""
    
    try:
        # First compilation run
        logger.info("Running first compilation pass")
        proc = subprocess.run(
            [compiler, "-interaction=nonstopmode", main_tex_path.name],
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=120
        )

        first_pass_logs = f"=== First Compilation Pass ({compiler}) ===\n"
        first_pass_logs += f"Return code: {proc.returncode}\n"
        first_pass_logs += f"STDOUT:\n{proc.stdout}\n"
        first_pass_logs += f"STDERR:\n{proc.stderr}\n\n"
        all_logs += first_pass_logs
        
        # Check if first pass failed critically
        if proc.returncode != 0:
            logger.error(f"First compilation pass failed with return code {proc.returncode}")
            return False, all_logs

        # Run bibliography processor if needed
        bib_run, bib_logs = run_bibtex_if_needed(working_dir, main_tex_name, compiler)
        if bib_run:
            all_logs += bib_logs
        else:
            all_logs += f"=== Bibliography Processing ===\n{bib_logs}\n"
        
        # Second compilation run (for cross-references and bibliography)
        logger.info("Running second compilation pass")
        proc = subprocess.run(
            [
                compiler,
                '-interaction=nonstopmode',
                main_tex_path.name
            ],
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=120
        )
        
        second_pass_logs = f"=== Second Compilation Pass ({compiler}) ===\n"
        second_pass_logs += f"Return code: {proc.returncode}\n"
        second_pass_logs += f"STDOUT:\n{proc.stdout}\n"
        second_pass_logs += f"STDERR:\n{proc.stderr}\n\n"
        all_logs += second_pass_logs
        
        if proc.returncode != 0:
            logger.error(f"Second compilation pass failed with return code {proc.returncode}")
            # Include first pass logs if second pass fails to provide full context
            all_logs = first_pass_logs + all_logs
            return False, all_logs
        
        # Third compilation run if bibliography was processed
        if bib_run:
            logger.info("Running third compilation pass (after bibliography)")
            proc = subprocess.run(
                [
                    compiler,
                    '-interaction=nonstopmode',
                    main_tex_path.name
                ],
                cwd=working_dir,
                capture_output=True,
                text=True,
                timeout=120
            )
            
            third_pass_logs = f"=== Third Compilation Pass ({compiler}) ===\n"
            third_pass_logs += f"Return code: {proc.returncode}\n"
            third_pass_logs += f"STDOUT:\n{proc.stdout}\n"
            third_pass_logs += f"STDERR:\n{proc.stderr}\n\n"
            all_logs += third_pass_logs
            
            if proc.returncode != 0:
                logger.warning("Third compilation pass failed, but continuing with existing PDF")
        
        # Check if PDF was actually generated
        pdf_path = working_dir / f"{main_tex_name}.pdf"
        if not pdf_path.exists():
            all_logs += "=== ERROR ===\nPDF file was not generated despite successful compilation\n"
            # Include first pass logs if PDF generation fails to provide full context
            all_logs = first_pass_logs + all_logs
            return False, all_logs
            
        all_logs += "=== COMPILATION SUCCESSFUL ===\n"
        compile_project.last_logs = all_logs
        return True, all_logs
        
    except subprocess.TimeoutExpired:
        all_logs += f"=== TIMEOUT ERROR ===\nCompilation timed out after 120 seconds\n"
        # Include first pass logs for timeout to provide full context
        all_logs = first_pass_logs + all_logs
        return False, all_logs
    except Exception as e:
        logger.error(f"Compilation error: {str(e)}")
        all_logs += f"=== UNEXPECTED ERROR ===\n{str(e)}\n"
        # Include first pass logs for unexpected errors to provide full context
        all_logs = first_pass_logs + all_logs
        return False, all_logs

@app.get("/")
async def root():
    """Health check endpoint."""
    return {"message": "LaTeX compilation service is running"}

@app.get("/compilers")
async def list_compilers():
    """List available LaTeX compilers."""
    compilers = ['pdflatex', 'xelatex', 'lualatex']
    available = []
    
    for compiler in compilers:
        try:
            proc = subprocess.run(
                [compiler, '--version'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5
            )
            if proc.returncode == 0:
                available.append(compiler)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
    
    return {"available_compilers": available}

@app.get("/info")
async def service_info():
    """Get service information and supported file types."""
    return {
        "service": "LaTeX Compilation Service",
        "endpoints": {
            "/compile-single": "Compile a single .tex file",
            "/compile-project": "Compile a project from structured folder data (JSON)"
        },
        "supported_extensions": list(ALLOWED_EXTENSIONS),
        "features": [
            "Automatic compiler detection (pdflatex/xelatex/lualatex)",
            "Bibliography processing (bibtex/biber)",
            "Multi-pass compilation for cross-references",
            "Project folder structure preservation",
            "JSON-based project structure",
            "Security validation"
        ],
        "data_format": {
            "PaperFolderData": "Root project structure",
            "FileInfo": "Individual file information with content"
        }
    }
