from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_from_directory
from functools import wraps
import json
import os
from datetime import datetime, timedelta
import uuid
from werkzeug.utils import secure_filename

import google.generativeai as genai
import requests
from bs4 import BeautifulSoup

import supabase
from config import Config
from werkzeug.security import generate_password_hash, check_password_hash
from supabase import create_client, Client
import logging

# ===== AI RATE LIMITING USING SUPABASE (PRODUCTION) =====
def check_ai_rate_limit(user_id, feature='ai_explain'):
    """Production rate limiting using Supabase database"""
    supabase = get_supabase()
    if not supabase:
        return True  # Fail open if no database connection
    
    try:
        now = datetime.now()
        one_hour_ago = (now - timedelta(hours=1)).isoformat()
        
        # Count usage in the last hour
        response = supabase.table('ai_usage_logs').select('id', count='exact').eq('user_id', user_id).eq('feature', feature).gte('timestamp', one_hour_ago).execute()
        
        # Get the count from response
        if hasattr(response, 'count'):
            usage_count = response.count
        else:
            usage_count = len(response.data) if response.data else 0
        
        # Limit: 20 requests per hour per feature
        if usage_count >= 20:
            return False
        
        # Log this usage
        supabase.table('ai_usage_logs').insert({
            'user_id': user_id,
            'feature': feature,
            'timestamp': now.isoformat()
        }).execute()
        
        return True
        
    except Exception as e:
        logger.error(f"Rate limit check failed: {e}")
        return True  # Fail open on error - never block users due to system errors

def get_user_by_username(username):
    """Get user by username (since we don't have id column)"""
    supabase = get_supabase()
    if not supabase or not username:
        return None
    try:
        response = supabase.table('users').select('*').eq('username', username).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        logger.error(f"Error getting user {username}: {e}")
        return None

# File upload configuration - ADD AT TOP OF FILE
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'txt', 'ppt', 'pptx', 'jpg', 'jpeg', 'png'}
MAX_FILE_SIZE = 16 * 1024 * 1024  # 16MB

# Create uploads directory if it doesn't exist
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)


app = Flask(__name__)

# ------------------------------------------------------
# ✅ CONFIGURATION SETUP - FIXED
# ------------------------------------------------------

# Method 1: Direct configuration (if Config import fails)
try:
    app.config.from_object(Config)
    print("✅ Config loaded successfully from config.py")
except Exception as e:
    print(f"⚠️ Config import failed: {e}")
    print("🔄 Using direct configuration...")
    # Fallback configuration
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or 'dev-key-change-in-production'
    app.config['SESSION_PERMANENT'] = True
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

# ------------------------------------------------------
# ✅ GOOGLE AI CONFIGURATION - FIXED
# ------------------------------------------------------

GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')

if GOOGLE_API_KEY:
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        # Test the configuration
        model = genai.GenerativeModel("gemini-1.5-flash-latest")
        print("✅ Google AI configured successfully with gemini-1.5-pro-latest")
    except Exception as e:
        print(f"❌ Google AI configuration failed: {e}")
        GOOGLE_API_KEY = None
else:
    print("⚠️ GOOGLE_API_KEY not found. AI features disabled.")

# ... rest of your app.py code continues normally ...


# ------------------------------------------------------
# ✅ EXTRACT TEXT FROM WEBPAGES (for study material URL uploads)
# ------------------------------------------------------

def extract_webpage_content(url):
    """Extract readable text content from a webpage."""
    try:
        response = requests.get(url, timeout=10)
        soup = BeautifulSoup(response.content, 'html.parser')

        # remove unnecessary tags
        for tag in soup(["script", "style"]):
            tag.decompose()

        # extract visible text, clean spacing
        text = soup.get_text()
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = " ".join(chunk for chunk in chunks if chunk)

        return text[:4000]  # limit size for AI
    except:
        return None

# Test available models
def test_gemini_models():
    """Test available Gemini models with 2025 API"""
    if not GOOGLE_API_KEY:
        print("❌ GOOGLE_API_KEY not set")
        return []

    try:
        # ✅ NEW 2025 WAY TO LIST MODELS
        models = genai.list_models()
        available_models = []
        
        print("✅ Available Gemini models (Nov 2025):")
        for model in models:
            if 'generateContent' in model.supported_generation_methods and 'gemini' in model.name:
                available_models.append(model.name)
                print(f"   • {model.name}")
        
        return available_models
    except Exception as e:
        print(f"❌ Failed to list models: {e}")
        return []

# Call this function after Google AI config
test_gemini_models()
# ------------------------------------------------------
# ✅ GENERATE AI EXPLANATION (Gemini)
# ------------------------------------------------------

def generate_ai_explanation(content, material_type, title):
    """Fully working AI explanation with your new API key"""
    if not GOOGLE_API_KEY:
        return get_fallback_explanation(title, material_type)

    # ✅ YOUR WORKING MODELS
    working_models = [
        "models/gemini-2.0-flash",           # Fast & reliable
        "models/gemini-2.5-flash",           # Latest flash
        "models/gemini-2.0-pro-exp",         # High quality
        "models/gemini-flash-latest",        # Always current
    ]

    content = content[:2500] if len(content) > 2500 else content

    prompt = f"""Explain this study material in a simple, engaging way for students:

Title: {title}
Type: {material_type}

Content:
{content}

Please provide:
1. A simple explanation of the main concepts
2. Key points to remember  
3. Real-world examples that students can relate to
4. Practical study tips

Make it fun, easy to understand, and student-friendly. Use emojis to make it engaging!
Keep it under 300 words."""

    for model_name in working_models:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            
            if response.text and len(response.text.strip()) > 50:
                print(f"✅ AI EXPLANATION SUCCESS with {model_name}")
                return response.text.strip()
                
        except Exception as e:
            print(f"❌ Model {model_name} failed: {e}")
            continue

    return get_fallback_explanation(title, material_type)

def generate_ai_summary(content, material_type, title):
    """Fully working AI summary with your new API key"""
    if not GOOGLE_API_KEY:
        return get_fallback_summary(title, material_type)

    content = content[:1800] if len(content) > 1800 else content

    prompt = f"""Create a simple 3-5 bullet summary for students:

Title: {title}
Type: {material_type}

Content:
{content}

Provide only the most important points as bullet points.
Make it clear, concise, and easy to remember.
Use emojis to make it engaging!"""

    for model_name in ["models/gemini-2.0-flash", "models/gemini-2.5-flash"]:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            if response.text and len(response.text.strip()) > 20:
                print(f"✅ AI SUMMARY SUCCESS with {model_name}")
                return response.text.strip()
        except Exception as e:
            print(f"❌ Summary model {model_name} failed: {e}")
            continue

    return get_fallback_summary(title, material_type)

def get_fallback_explanation(title, material_type):
    """Provide helpful fallback explanations"""
    fallbacks = {
        'text': f"""
        **📚 Understanding '{title}'**

        **Main Concepts:**
        This material covers important concepts that your teacher wants you to understand. Take your time to read through it carefully.

        **Key Points to Remember:**
        • Focus on the main ideas presented
        • Note down any important definitions
        • Look for examples that illustrate the concepts

        **Study Tips:**
        • Read through the material at least twice
        • Create your own summary notes
        • Discuss with classmates for better understanding
        • Ask your teacher about anything unclear

        💡 **Tip:** Try explaining the concepts in your own words to reinforce learning!
        """,
        
        'file': f"""
        **📄 About '{title}'**

        **What this file contains:**
        This file includes important learning materials shared by your teacher. It might be notes, exercises, or reference material.

        **How to use it:**
        • Download and open the file
        • Look for key sections and headings
        • Pay attention to examples and exercises
        • Use it for review and practice

        **Study Tips:**
        • Take notes as you go through the file
        • Highlight important information
        • Try any exercises included
        • Refer back to it when studying

        📝 **Remember:** Active engagement with the material helps learning!
        """,
        
        'video': f"""
        **🎥 Video: '{title}'**

        **What to expect:**
        This video explains important concepts visually. Videos can help you understand complex topics through demonstrations and examples.

        **How to get the most from this video:**
        • Watch it actively, not passively
        • Pause and take notes
        • Re-watch confusing sections
        • Connect it to what you've learned in class

        **Key things to look for:**
        • Main concepts being explained
        • Examples and demonstrations
        • Important terms and definitions
        • Summary points

        ⏯️ **Tip:** Take breaks during longer videos to process information!
        """,
        
        'web': f"""
        **🌐 Web Resource: '{title}'**

        **About this resource:**
        This online resource provides additional information on the topic. It might include articles, interactive content, or reference materials.

        **How to use it effectively:**
        • Skim through first to understand the structure
        • Read carefully for important details
        • Take notes on key points
        • Look for examples and applications

        **What to focus on:**
        • Main ideas and concepts
        • Supporting examples
        • Definitions of key terms
        • Any practice questions or activities

        🔍 **Remember:** Not everything online is equally valuable - focus on the core concepts!
        """
    }
    
    return fallbacks.get(material_type, fallbacks['text'])

def get_fallback_summary(title, material_type):
    """Provide helpful fallback summaries"""
    summaries = {
        'text': f"""
        • **{title}** covers key concepts in this subject
        • Focus on understanding the main ideas presented
        • Note important definitions and examples
        • Review the material regularly for better retention
        • Ask questions about anything unclear
        """,
        
        'file': f"""
        • **{title}** contains important learning materials
        • Download and review the file carefully
        • Look for key sections and examples
        • Use it for practice and review
        • Keep it for future reference
        """,
        
        'video': f"""
        • **{title}** explains concepts visually
        • Watch actively and take notes
        • Pay attention to demonstrations
        • Re-watch confusing sections
        • Connect to classroom learning
        """,
        
        'web': f"""
        • **{title}** provides online learning resources
        • Browse for main concepts and examples
        • Focus on reliable information
        • Take notes on key points
        • Use as supplementary material
        """
    }
    
    return summaries.get(material_type, summaries['text'])



# Configure upload settings
# Configure upload settings with enhanced security
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'txt', 'ppt', 'pptx', 'jpg', 'jpeg', 'png'}
MAX_FILE_SIZE = 16 * 1024 * 1024  # 16MB

def allowed_file(filename):
    """Check if file extension is allowed"""
    if not filename or '.' not in filename:
        return False
    extension = filename.rsplit('.', 1)[1].lower()
    return extension in ALLOWED_EXTENSIONS

def validate_file_size(file_storage):
    """Validate file size before upload"""
    if not file_storage:
        return False
        
    # Save current position
    current_pos = file_storage.tell()
    file_storage.seek(0, 2)  # Seek to end
    file_size = file_storage.tell()
    file_storage.seek(current_pos)  # Reset to original position
    
    return file_size <= MAX_FILE_SIZE

# Add this function to debug available models
def list_available_models():
    """List available Gemini models"""
    try:
        if GOOGLE_API_KEY:
            models = genai.list_models()
            available_models = []
            for model in models:
                if 'generateContent' in model.supported_generation_methods:
                    available_models.append(model.name)
            print("✅ Available Gemini models for generateContent:")
            for model_name in available_models:
                print(f"   - {model_name}")
            return available_models
        return []
    except Exception as e:
        print(f"❌ Error listing models: {e}")
        return []

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Supabase client
# Initialize Supabase client with better error handling
# Initialize Supabase client with better error handling
def get_supabase():
    """Initialize and return Supabase client with enhanced error handling"""
    try:
        url = os.environ.get('SUPABASE_URL')
        key = os.environ.get('SUPABASE_KEY')
        
        print(f"DEBUG: SUPABASE_URL exists: {bool(url)}")
        print(f"DEBUG: SUPABASE_KEY exists: {bool(key)}")
        
        if not url or not key:
            logger.error("Missing Supabase environment variables: SUPABASE_URL or SUPABASE_KEY")
            return None
            
        print(f"DEBUG: Creating client with URL: {url[:20]}... and key: {key[:10]}...")
        client = create_client(url, key)
        print("DEBUG: Client created successfully")
        
        # Test connection with a simple query
        try:
            test_response = client.table('users').select('username').limit(1).execute()
            logger.info("✅ Supabase connection successful")
        except Exception as test_error:
            logger.error(f"Supabase connection test failed: {test_error}")
            return None
            
        return client
        
    except Exception as e:
        logger.error(f"Error initializing Supabase client: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return None

# ===== ENHANCED DECORATORS =====
def super_admin_required(f):
    """Only for sirius - the platform owner - STRICT CHECK"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session['user_id'] != 'sirius':
            flash('Super admin access required.', 'danger')
            return redirect(url_for('index'))
        
        # Additional security: Verify sirius role in database
        supabase = get_supabase()
        if supabase:
            try:
                user_response = supabase.table('users').select('school_id').eq('username', 'sirius').execute()
                if user_response.data:
                    user = user_response.data[0]
                    # Ensure sirius has no school association (pure super admin)
                    if user.get('school_id'):
                        flash('Super admin configuration error.', 'danger')
                        return redirect(url_for('index'))
            except Exception as e:
                logger.error(f"Super admin verification error: {e}")
        
        return f(*args, **kwargs)
    return decorated_function


# ===== NEW DECORATORS =====
def school_admin_required(f):
    """For school-level admins - ALLOWS sirius with school context"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in first.', 'warning')
            return redirect(url_for('login'))
        
        # ALLOW sirius to access school admin features when he has a school context
        if session['user_id'] == 'sirius':
            # Only allow if sirius has selected a school
            if not session.get('current_school_id'):
                flash('Please select a school first using the school switcher.', 'warning')
                return redirect(url_for('super_admin_dashboard'))
            return f(*args, **kwargs)  # Sirius can access
        
        # Regular school admin check for other users
        supabase = get_supabase()
        if not supabase:
            flash('Database connection error.', 'danger')
            return redirect(url_for('index'))
            
        try:
            user_response = supabase.table('users').select('*').eq('username', session['user_id']).execute()
            user = user_response.data[0] if user_response.data else None
            
            # Check if user is school admin (is_admin = True AND role = teacher)
            if not user or user['role'] != 'teacher' or not user.get('is_admin'):
                flash('School admin access required.', 'danger')
                return redirect(url_for('teacher_dashboard'))
            return f(*args, **kwargs)
        except Exception as e:
            logger.error(f"School admin check error: {e}")
            flash('Error verifying permissions.', 'danger')
            return redirect(url_for('teacher_dashboard'))
    return decorated_function

def student_required(f):
    """Enhanced student access control - ALLOWS SIRIUS"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in first.', 'warning')
            return redirect(url_for('login'))
        
        # ALLOW sirius to access student features
        if session['user_id'] == 'sirius':
            return f(*args, **kwargs)  # Sirius can access student routes
        
        supabase = get_supabase()
        if not supabase:
            flash('Database connection error.', 'danger')
            return redirect(url_for('index'))
            
        try:
            user_response = supabase.table('users').select('*').eq('username', session['user_id']).execute()
            user = user_response.data[0] if user_response.data else None
            
            if not user or user['role'] != 'student':
                flash('Student access required.', 'danger')
                return redirect(url_for('teacher_dashboard'))
            return f(*args, **kwargs)
        except Exception as e:
            logger.error(f"Student check error: {e}")
            flash('Error verifying permissions.', 'danger')
            return redirect(url_for('index'))
    return decorated_function

def teacher_required(f):
    """Enhanced to ensure school scoping - ALLOWS sirius with school context"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        
        # ALLOW sirius to access teacher features when he has a school context
        if session['user_id'] == 'sirius':
            return f(*args, **kwargs)  # Sirius can always access teacher routes
        
        # Regular teacher check for other users
        supabase = get_supabase()
        if not supabase:
            flash('Database connection error.', 'danger')
            return redirect(url_for('index'))
            
        try:
            user_response = supabase.table('users').select('*').eq('username', session['user_id']).execute()
            user = user_response.data[0] if user_response.data else None
            
            if not user or user['role'] != 'teacher':
                flash('Teacher access required.', 'danger')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        except Exception as e:
            logger.error(f"Teacher check error: {e}")
            flash('Error verifying permissions.', 'danger')
            return redirect(url_for('index'))
    return decorated_function

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# app/context_processors.py

@app.context_processor
def inject_user_info():
    """Enhanced context processor with better error handling"""
    context = {
        "is_school_admin": False,
        "user_school_id": None,
        "teacher_permissions": "classroom",
        "is_classroom_teacher": True,
        "available_schools": [],
        "current_school_id": None,
        "current_school_name": None,
        "available_teachers": [],
        "current_teacher_id": None,
        "current_teacher_name": None,
    }

    # No user in session
    if "user_id" not in session:
        return context

    supabase = get_supabase()
    if not supabase:
        logger.warning("No Supabase connection in context processor")
        return context

    try:
        # ---------------------------------------------------------------------
        # SIRIUS OVERRIDE
        # ---------------------------------------------------------------------
        if session["user_id"] == "sirius":
            # Always admin
            context.update({
                "is_school_admin": True,
                "teacher_permissions": "admin",
                "is_classroom_teacher": False,
            })

            # Load all schools for school switcher
            try:
                schools_response = supabase.table("schools").select("*").order("name").execute()
                context["available_schools"] = schools_response.data or []
            except Exception as e:
                logger.error(f"Error loading schools for Sirius: {e}")
                context["available_schools"] = []

            # If a school is selected in session
            current_school_id = session.get("current_school_id")
            if current_school_id:
                context["current_school_id"] = current_school_id

                # Find current school name
                current_school = next(
                    (s for s in context["available_schools"] if s["id"] == current_school_id),
                    None,
                )
                if current_school:
                    context["current_school_name"] = current_school["name"]

                # Load all teachers in selected school
                try:
                    teachers_response = (
                        supabase.table("users")
                        .select("username")
                        .eq("school_id", current_school_id)
                        .eq("role", "teacher")
                        .execute()
                    )
                    context["available_teachers"] = teachers_response.data or []
                except Exception as e:
                    logger.error(f"Error loading teachers for Sirius: {e}")
                    context["available_teachers"] = []

            # Teacher selection
            current_teacher_id = session.get("current_teacher_id")
            if current_teacher_id:
                context["current_teacher_id"] = current_teacher_id
                context["current_teacher_name"] = current_teacher_id

            return context

        # ---------------------------------------------------------------------
        # REGULAR USER LOGIC
        # ---------------------------------------------------------------------
        user_response = (
            supabase.table("users")
            .select("is_admin, school_id, teacher_permissions")
            .eq("username", session["user_id"])
            .execute()
        )
        
        if not user_response.data:
            logger.warning(f"User {session['user_id']} not found in database")
            return context
            
        user = user_response.data[0]

        # School admin logic (NOT Sirius)
        is_school_admin = user.get("is_admin", False) and session.get("role") == "teacher"
        teacher_permissions = user.get("teacher_permissions", "classroom")

        context.update({
            "is_school_admin": is_school_admin,
            "user_school_id": user.get("school_id"),
            "teacher_permissions": teacher_permissions,
            "is_classroom_teacher": teacher_permissions == "classroom",
        })

        # If user is school admin, load teachers from their school
        if is_school_admin and user.get("school_id"):
            school_id = user["school_id"]
            context["current_school_id"] = school_id

            try:
                teachers_response = (
                    supabase.table("users")
                    .select("username")
                    .eq("school_id", school_id)
                    .eq("role", "teacher")
                    .execute()
                )
                context["available_teachers"] = teachers_response.data or []
            except Exception as e:
                logger.error(f"Error loading teachers for school admin: {e}")
                context["available_teachers"] = []

        # Teacher switching context
        current_teacher_id = session.get("current_teacher_id")
        if current_teacher_id:
            context["current_teacher_id"] = current_teacher_id
            context["current_teacher_name"] = current_teacher_id

    except Exception as e:
        logger.error(f"Context processor error: {e}")

    return context



# ===== DATABASE FIX ROUTES =====
@app.route('/fix-schools-table')
def fix_schools_table():
    """Add missing columns to schools table"""
    supabase = get_supabase()
    if not supabase:
        return "Database connection failed"
    
    try:
        # First, let's see what columns actually exist
        test_school = supabase.table('schools').select('*').limit(1).execute()
        if test_school.data:
            existing_columns = list(test_school.data[0].keys())
            return f"""
            <h3>Current Schools Table Columns:</h3>
            <pre>{existing_columns}</pre>
            <p>If 'status' is missing, you need to run this SQL in Supabase:</p>
            <pre>
ALTER TABLE schools ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending';
ALTER TABLE schools ADD COLUMN IF NOT EXISTS contact_person TEXT;
ALTER TABLE schools ADD COLUMN IF NOT EXISTS contact_phone TEXT;
            </pre>
            """
        else:
            return "No schools found. Try creating one first."
                
    except Exception as e:
        error_msg = str(e)
        if 'status' in error_msg:
            return """
            <h3>❌ Missing 'status' Column</h3>
            <p>You need to add the 'status' column to your schools table.</p>
            <p>Go to <strong>Supabase → SQL Editor</strong> and run this:</p>
            <pre>
ALTER TABLE schools ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending';
ALTER TABLE schools ADD COLUMN IF NOT EXISTS contact_person TEXT;
ALTER TABLE schools ADD COLUMN IF NOT EXISTS contact_phone TEXT;
            </pre>
            <p>Then refresh this page to check.</p>
            """
        return f"Error: {error_msg}"

@app.route('/setup-database')
def setup_database():
    """Check if database is working"""
    supabase = get_supabase()
    if not supabase:
        return "❌ Database connection failed"
    
    try:
        # Test schools table
        schools = supabase.table('schools').select('*').execute()
        # Test users table  
        users = supabase.table('users').select('*').execute()
        
        return f"""
        <h3>✅ Database Connection Working</h3>
        <p>Schools table: {len(schools.data) if schools.data else 0} records</p>
        <p>Users table: {len(users.data) if users.data else 0} records</p>
        <p><strong>Database is ready!</strong></p>
        """
    except Exception as e:
        return f"❌ Database error: {str(e)}"

@app.route('/debug-data')
@super_admin_required
def debug_data():
    """Styled system debug page"""
    supabase = get_supabase()
    if not supabase:
        return "No database connection"
    
    try:
        schools = supabase.table('schools').select('*').execute()
        users = supabase.table('users').select('username, role, school_id, is_admin, approval_status').execute()
        
        # Calculate counts
        teachers_count = len([u for u in (users.data or []) if u.get('role') == 'teacher'])
        students_count = len([u for u in (users.data or []) if u.get('role') == 'student'])
        
        return render_template('debug_data.html',
                             schools=schools.data if schools.data else [],
                             users=users.data if users.data else [],
                             teachers_count=teachers_count,
                             students_count=students_count)
    except Exception as e:
        return f"Error: {str(e)}"

# ===== DEMO SCHOOL SETUP =====
@app.route('/create-demo-school')
def create_demo_school():
    """Quickly create a demo school for testing"""
    supabase = get_supabase()
    if not supabase:
        return "Database connection failed"
    
    try:
        # Check if demo school already exists
        existing = supabase.table('schools').select('id, name').eq('name', 'Newel Academy').execute()
        if existing.data:
            return "Demo school already exists!"
        
        # Create demo school - only use columns that definitely exist
        school_data = {
            'id': 'school_demo_academy',
            'name': 'Newel Academy', 
            'created_at': datetime.now().isoformat()
        }
        
        # Try to add status if column exists
        try:
            school_data['status'] = 'active'
        except:
            pass  # Column doesn't exist yet
            
        school_result = supabase.table('schools').insert(school_data).execute()
        
        if school_result.data:
            return """
            <h3>✅ Demo School Created!</h3>
            <p><strong>School Name:</strong> Newel Academy</p>
            <p><strong>School ID:</strong> school_demo_academy</p>
            <p>You can now register teachers and students for this school.</p>
            <a href="/register" class="btn btn-primary">Register Users</a>
            <br><br>
            <small>Note: You may need to <a href="/fix-schools-table">add missing columns</a> for full functionality.</small>
            """
        else:
            return "Failed to create demo school"
            
    except Exception as e:
        return f"Error: {str(e)}<br><br>You may need to <a href='/fix-schools-table'>fix the database schema</a> first."

# ===== MAIN ROUTES =====
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        supabase = get_supabase()
        if not supabase:
            flash('Database connection error. Please try again.', 'danger')
            return render_template('register.html')

        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        role = request.form.get('role')
        grade = request.form.get('grade') if role == 'student' else None
        security_question = request.form.get('security_question', '').strip()
        security_answer = request.form.get('security_answer', '').strip()
        school_id = request.form.get('school_id')
        
        # Get subjects for teachers
        subjects = []
        if role == 'teacher':
            subjects = request.form.getlist('subjects')  # Get multiple selections

        # Basic validation
        if not username or not password:
            flash('Username and password are required.', 'danger')
            return render_template('register.html')

        if role == 'student' and not grade:
            flash('Please select your grade level.', 'danger')
            return render_template('register.html')

        try:
            # Check existing username
            response = supabase.table('users').select('username').eq('username', username).execute()
            if response.data:
                flash('Username already exists. Please choose another.', 'danger')
                return render_template('register.html')

            # Base user data
            user_data = {
                'username': username,
                'password_hash': generate_password_hash(password),
                'role': role,
                'approval_status': 'pending',
                'created_at': datetime.now().isoformat(),
                'school_id': school_id
            }

            # Add grade if student
            if role == 'student' and grade:
                user_data['grade'] = grade

            # Add subjects if teacher
            if role == 'teacher' and subjects:
                user_data['subjects'] = subjects  # This will be stored as array in Supabase

            # ✅ ADD SECURITY QUESTION FOR ALL USERS (not just students)
            if security_question and security_answer:
                user_data['security_question'] = security_question
                user_data['security_answer_hash'] = generate_password_hash(
                    security_answer.lower().strip()
                )

            # Insert into database
            result = supabase.table('users').insert(user_data).execute()

            if result.data:
                flash('Registration successful! Please wait for admin approval.', 'success')
                return redirect(url_for('login'))
            else:
                flash('Registration failed. Please try again.', 'danger')

        except Exception as e:
            logger.error(f"Registration error: {e}")
            flash('Registration error. Please try again.', 'danger')

    # GET request — Fetch schools for dropdown
    supabase = get_supabase()
    schools = []
    if supabase:
        try:
            schools_response = supabase.table('schools').select('*').execute()
            schools = schools_response.data if schools_response.data else []
        except Exception as e:
            logger.error(f"Error fetching schools: {e}")
            schools = []

    return render_template('register.html', schools=schools)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        supabase = get_supabase()
        if not supabase:
            flash('Database connection error. Please try again.', 'danger')
            return render_template('login.html')
        
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        try:
            # Get user from Supabase
            response = supabase.table('users').select('*').eq('username', username).execute()
            user = response.data[0] if response.data else None
            
            if user and check_password_hash(user['password_hash'], password):
                # Check if user is approved
                if user.get('approval_status') != 'approved':
                    flash('Your account is pending admin approval. Please wait for activation.', 'warning')
                    return render_template('login.html')
                
                session['user_id'] = username
                session['role'] = user['role']
                flash(f'Welcome back, {username}!', 'success')
                
                # 🎯 FIX: Super Admin goes to super admin dashboard
                if username == 'sirius':
                    return redirect(url_for('super_admin_dashboard'))
                elif user['role'] == 'teacher':
                    return redirect(url_for('teacher_dashboard'))
                else:
                    return redirect(url_for('student_dashboard'))
            else:
                flash('Invalid username or password.', 'danger')
                
        except Exception as e:
            logger.error(f"Login error: {e}")
            flash('Login error. Please try again.', 'danger')
    
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        
        supabase = get_supabase()
        if not supabase:
            flash('Database connection error.', 'danger')
            return render_template('forgot_password.html')
        
        try:
            # Check if user exists and has security question
            user_response = supabase.table('users').select('*').eq('username', username).execute()
            user = user_response.data[0] if user_response.data else None
            
            if user and user.get('security_question'):
                # Store username in session for verification
                session['reset_username'] = username
                return render_template('security_question.html', 
                                    question=user['security_question'],
                                    username=username)
            else:
                # Don't reveal if user exists for security
                flash('If that username exists and has a security question set, you will be redirected to answer it.', 'info')
                return redirect(url_for('forgot_password'))
                
        except Exception as e:
            logger.error(f"Password reset error: {e}")
            flash('Error processing reset request.', 'danger')
    
    return render_template('forgot_password.html')


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('forgot_password'))
    
    try:
        # Verify token is valid and not expired
        response = supabase.table('users').select('*').eq('reset_token', token).execute()
        user = response.data[0] if response.data else None
        
        if not user or datetime.fromisoformat(user['reset_token_expiry']) < datetime.now():
            flash('Invalid or expired reset link.', 'danger')
            return redirect(url_for('forgot_password'))
        
        if request.method == 'POST':
            new_password = request.form.get('password', '').strip()
            confirm_password = request.form.get('confirm_password', '').strip()
            
            if not new_password or not confirm_password:
                flash('Please fill in all fields.', 'danger')
                return render_template('reset_password.html', token=token)
            
            if new_password != confirm_password:
                flash('Passwords do not match.', 'danger')
                return render_template('reset_password.html', token=token)
            
            # Update password and clear reset token
            supabase.table('users').update({
                'password_hash': generate_password_hash(new_password),
                'reset_token': None,
                'reset_token_expiry': None
            }).eq('reset_token', token).execute()
            
            flash('Password reset successfully! Please login with your new password.', 'success')
            return redirect(url_for('login'))
        
        return render_template('reset_password.html', token=token)
        
    except Exception as e:
        logger.error(f"Reset password error: {e}")
        flash('Error resetting password.', 'danger')
        return redirect(url_for('forgot_password'))

# routes/teacher_dashboard.py

@app.route('/teacher/dashboard')
@teacher_required
def teacher_dashboard():
    supabase = get_supabase()

    try:
        user_id = session.get('user_id')
        if not user_id:
            flash("Session expired. Please log in again.", "danger")
            return redirect(url_for('login'))

        # Get the CORRECT teacher context
        current_viewing_teacher = session.get('current_teacher_id') or user_id
        
        # Get teacher info
        teacher = get_user_by_username(current_viewing_teacher)
        if not teacher:
            flash("Teacher record not found.", "danger")
            return redirect(url_for('index'))

        school_id = teacher.get("school_id")
        is_school_admin = teacher.get("is_admin", False)

        print(f"DEBUG: Viewing teacher {current_viewing_teacher}, school_id: {school_id}")

        # Get prompts for the CORRECT school
        prompts_response = supabase.table("prompts").select("*").eq("school_id", school_id).execute()
        prompts = prompts_response.data if prompts_response.data else []

        # Apply filters
        grade_filter = request.args.get('grade', 'all')
        category_filter = request.args.get('category', 'all')

        filtered_prompts = prompts.copy()

        if grade_filter != "all":
            filtered_prompts = [p for p in filtered_prompts if str(p.get("grade_level")) == str(grade_filter)]

        if category_filter != "all":
            filtered_prompts = [p for p in filtered_prompts if p.get("assessment_type") == category_filter]

        # Get unique values for filters
        unique_grades = sorted(list({p["grade_level"] for p in prompts if p.get("grade_level")}))
        unique_categories = sorted(list({p["assessment_type"] for p in prompts if p.get("assessment_type")}))

        # Count assessment types from ALL prompts
        written_count = len([p for p in prompts if p.get("assessment_type") == "written"])
        mcq_count = len([p for p in prompts if p.get("assessment_type") == "mcq"])
        mixed_count = len([p for p in prompts if p.get("assessment_type") == "mixed"])

        # Get submissions for each prompt - FIXED: No join needed
        prompt_stats = {}
        all_school_submissions = []  # Track all submissions for this school
        
        for prompt in prompts:
            submissions_res = supabase.table("submissions").select("*").eq("prompt_id", prompt['id']).execute()
            submissions = submissions_res.data if submissions_res.data else []
            all_school_submissions.extend(submissions)  # Collect for school totals
            
            graded = len([s for s in submissions if s.get('grade') is not None])
            total = len(submissions)

            prompt_stats[prompt['id']] = {
                "graded": graded,
                "total": total
            }

        # Get students from the CORRECT school
        students_res = supabase.table("users").select("*").eq("school_id", school_id).eq("role", "student").execute()
        all_students = students_res.data if students_res.data else []
        
        active_students = len([s for s in all_students if s.get('approval_status') == 'approved'])
        
        # 🎯 FIXED: Calculate completion rate properly
        total_possible_submissions = len(prompts) * len(all_students)
        actual_submissions = len(all_school_submissions)
        
        completion_rate = 0
        if total_possible_submissions > 0:
            completion_rate = round((actual_submissions / total_possible_submissions) * 100)

        class_analytics = {
            "total_students": len(all_students),
            "active_students": active_students,
            "total_submissions": len(all_school_submissions),
            "average_completion_rate": completion_rate  # 🎯 Now calculated properly
        }

        # Student progress (basic)
        student_progress = []
        for student in all_students[:5]:  # Show first 5 students
            student_submissions = len([s for s in all_school_submissions if s['student_id'] == student['username']])
            
            # Calculate student's completion rate
            student_prompts = [p for p in prompts if p.get('grade_level') == student.get('grade')]
            student_completion = 0
            if student_prompts:
                student_completion = round((student_submissions / len(student_prompts)) * 100)
            
            student_progress.append({
                'username': student['username'],
                'grade_level': student.get('grade', 'N/A'),
                'submissions_count': student_submissions,
                'average_grade': 75,  # Placeholder
                'completion_rate': student_completion
            })

        # Study materials count
        materials_response = supabase.table("study_materials").select("id").eq("school_id", school_id).execute()
        materials_count = len(materials_response.data) if materials_response.data else 0

        return render_template(
            "teacher_dashboard.html",
            prompts=filtered_prompts,
            prompt_stats=prompt_stats,
            current_grade_filter=grade_filter,
            current_category_filter=category_filter,
            available_grades=unique_grades,
            available_categories=unique_categories,
            student_progress=student_progress,
            class_analytics=class_analytics,
            written_count=written_count,
            mcq_count=mcq_count,
            mixed_count=mixed_count,
            is_school_admin=is_school_admin,
            materials_count=materials_count
        )

    except Exception as e:
        logger.error(f"Teacher dashboard error: {e}")
        flash("Error loading dashboard.", "danger")
        return redirect(url_for("index"))


@app.route('/teacher/create_prompt', methods=['GET', 'POST'])
@teacher_required
def create_prompt():
    if request.method == 'POST':
        supabase = get_supabase()
        if not supabase:
            flash('Database connection error.', 'danger')
            return render_template('create_prompt.html')
        
        # Get current user for school_id
        user_response = supabase.table('users').select('*').eq('username', session['user_id']).execute()
        user = user_response.data[0] if user_response.data else None

        if not user:
            flash("User not found. Please log in again.", "danger")
            return redirect(url_for('logout'))

        # Get basic prompt data
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        grade_level = request.form.get('grade_level')
        subject = request.form.get('subject', 'general')
        assessment_type = request.form.get('assessment_type', 'written')
        total_points = request.form.get('total_points', 10)
        instructions = request.form.get('instructions', '').strip()
        due_date_str = request.form.get('due_date', '').strip()

        if not all([title, description, grade_level]):
            flash('Title, description and grade level are required.', 'danger')
            return render_template('create_prompt.html')

        try:
            prompt_id = f"prompt_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            
            # Process due date
            due_date = None
            if due_date_str:
                due_date = datetime.fromisoformat(due_date_str).isoformat()
            
            # Create prompt with ALL fields (no try/except blocks)
            prompt_data = {
                'id': prompt_id,
                'title': title,
                'description': description,
                'grade_level': grade_level,
                'subject': subject,  # FIXED: Direct assignment
                'assessment_type': assessment_type,  # FIXED: Direct assignment
                'total_points': int(total_points),  # FIXED: Direct assignment
                'instructions': instructions if instructions else None,  # FIXED: Direct assignment
                'due_date': due_date,  # FIXED: Direct assignment
                'created_by': session['user_id'],
                'created_at': datetime.now().isoformat(),
                'school_id': user['school_id'],
            }

            logger.info(f"Creating prompt with data: {prompt_data}")
            prompt_result = supabase.table('prompts').insert(prompt_data).execute()
            
            if not prompt_result.data:
                flash('Failed to create assessment.', 'danger')
                return render_template('create_prompt.html')

            # Handle MCQ questions if assessment type includes them
            if assessment_type in ['mcq', 'mixed']:
                question_texts = request.form.getlist('question_text[]')
                question_types = request.form.getlist('question_type[]')
                question_points = request.form.getlist('question_points[]')
                correct_answers = request.form.getlist('correct_answer[]')
                option_as = request.form.getlist('option_a[]')
                option_bs = request.form.getlist('option_b[]')
                option_cs = request.form.getlist('option_c[]')
                option_ds = request.form.getlist('option_d[]')
                
                mcq_questions = []
                for i, (q_text, q_type, points, correct_ans) in enumerate(zip(
                    question_texts, question_types, question_points, correct_answers
                )):
                    if q_text.strip():  # Only add if question text exists
                        question_id = f"q_{prompt_id}_{i}"
                        question_data = {
                            'id': question_id,
                            'prompt_id': prompt_id,
                            'question_text': q_text.strip(),
                            'question_type': q_type,
                            'points': int(points),
                            'sort_order': i,
                            'correct_answer': correct_ans if q_type in ['mcq', 'true_false'] else None,
                            'created_at': datetime.now().isoformat()
                        }
                        
                        # Add options for MCQ and True/False questions
                        if q_type in ['mcq', 'true_false']:
                            question_data.update({
                                'option_a': option_as[i] if i < len(option_as) else '',
                                'option_b': option_bs[i] if i < len(option_bs) else '',
                                'option_c': option_cs[i] if i < len(option_cs) and option_cs[i] else None,
                                'option_d': option_ds[i] if i < len(option_ds) and option_ds[i] else None,
                            })
                        
                        mcq_questions.append(question_data)
                
                if mcq_questions:
                    supabase.table('mcq_questions').insert(mcq_questions).execute()

            logger.info(f"Prompt {prompt_id} created successfully with subject: {subject}")
            flash('Assessment created successfully!', 'success')
            return redirect(url_for('teacher_dashboard'))

        except Exception as e:
            logger.error(f"Prompt creation error: {e}")
            flash(f'Error creating assessment: {str(e)}', 'danger')

    return render_template('create_prompt.html')


@app.route('/teacher/edit_prompt/<prompt_id>', methods=['GET', 'POST'])
@teacher_required
def edit_prompt(prompt_id):
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('teacher_dashboard'))
    
    try:
        # Get the current prompt
        prompt_response = supabase.table('prompts').select('*').eq('id', prompt_id).execute()
        prompt = prompt_response.data[0] if prompt_response.data else None
        
        if not prompt:
            flash('Prompt not found.', 'danger')
            return redirect(url_for('teacher_dashboard'))
        
        # Check if user owns this prompt
        if prompt['created_by'] != session['user_id']:
            flash('You can only edit prompts you created.', 'danger')
            return redirect(url_for('teacher_dashboard'))
        
        if request.method == 'POST':
            title = request.form.get('title', '').strip()
            description = request.form.get('description', '').strip()
            grade_level = request.form.get('grade_level')
            subject = request.form.get('subject', 'general')
            due_date_str = request.form.get('due_date')
            
            if not title or not description or not grade_level:
                flash('All fields are required.', 'danger')
                return render_template('edit_prompt.html', prompt=prompt)

            # Process due date
            due_date = None
            if due_date_str:
                try:
                    due_date = datetime.fromisoformat(due_date_str.replace('Z', '+00:00'))
                except ValueError:
                    flash('Invalid due date format.', 'danger')
                    return render_template('edit_prompt.html', prompt=prompt)
            
            # Update prompt in Supabase - REMOVE updated_at if column doesn't exist
            update_data = {
                'title': title,
                'description': description,
                'grade_level': grade_level,
                'subject': subject,
                'due_date': due_date.isoformat() if due_date else None
            }
            
            # Only add updated_at if the column exists
            try:
                # Test if updated_at column exists by making a small update
                test_update = supabase.table('prompts').update({'title': title}).eq('id', prompt_id).execute()
                # If no error, try to add updated_at
                update_data['updated_at'] = datetime.now().isoformat()
            except:
                # Column doesn't exist, continue without it
                pass
            
            result = supabase.table('prompts').update(update_data).eq('id', prompt_id).execute()
            
            if result.data:
                flash('Prompt updated successfully!', 'success')
                return redirect(url_for('teacher_dashboard'))
            else:
                flash('Failed to update prompt.', 'danger')
        
        return render_template('edit_prompt.html', prompt=prompt)
        
    except Exception as e:
        logger.error(f"Edit prompt error: {e}")
        flash('Error editing prompt.', 'danger')
        return redirect(url_for('teacher_dashboard'))

@app.route('/teacher/delete_prompt/<prompt_id>', methods=['POST'])
@teacher_required
def delete_prompt(prompt_id):
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('teacher_dashboard'))
    
    try:
        # First, check if there are any submissions for this prompt
        submissions_response = supabase.table('submissions').select('id').eq('prompt_id', prompt_id).execute()
        
        if submissions_response.data:
            flash('Cannot delete prompt - students have already submitted responses to it.', 'warning')
            return redirect(url_for('teacher_dashboard'))
        
        # Delete the prompt from Supabase
        result = supabase.table('prompts').delete().eq('id', prompt_id).execute()
        
        if result.data:
            flash('Prompt deleted successfully!', 'success')
        else:
            flash('Prompt not found or already deleted.', 'warning')
            
    except Exception as e:
        logger.error(f"Delete prompt error: {e}")
        flash('Error deleting prompt.', 'danger')
    
    return redirect(url_for('teacher_dashboard'))

@app.route('/teacher/grade/<prompt_id>', methods=['GET', 'POST'])
@teacher_required
def grade_submissions(prompt_id):
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('teacher_dashboard'))
    
    try:
        # Get prompt
        prompt_response = supabase.table('prompts').select('*').eq('id', prompt_id).execute()
        prompt = prompt_response.data[0] if prompt_response.data else None
        
        if not prompt:
            flash('Prompt not found.', 'danger')
            return redirect(url_for('teacher_dashboard'))
        
        if request.method == 'POST':
            submission_id = request.form.get('submission_id')
            grade = request.form.get('grade')
            feedback = request.form.get('feedback', '').strip()
            
            if submission_id:
                try:
                    grade_value = float(grade) if grade else None
                    if grade_value is not None and (grade_value < 0 or grade_value > 100):
                        flash('Grade must be between 0 and 100.', 'danger')
                    else:
                        # Update submission in Supabase
                        update_data = {}
                        if grade_value is not None:
                            update_data['grade'] = grade_value
                        if feedback:
                            update_data['feedback'] = feedback
                        update_data['graded_at'] = datetime.now().isoformat()
                        
                        result = supabase.table('submissions').update(update_data).eq('id', submission_id).execute()
                        
                        if result.data:
                            flash('Submission graded successfully!', 'success')
                        else:
                            flash('Failed to grade submission.', 'danger')
                except ValueError:
                    flash('Invalid grade value.', 'danger')
            
            return redirect(url_for('grade_submissions', prompt_id=prompt_id))
        
        # Get submissions for this prompt with student info
        submissions_response = supabase.table('submissions').select('*').eq('prompt_id', prompt_id).execute()
        prompt_submissions = []
        
        for sub in submissions_response.data:
            # Get student info
            user_response = supabase.table('users').select('grade').eq('username', sub['student_id']).execute()
            student_grade = user_response.data[0]['grade'] if user_response.data else 'N/A'
            
            prompt_submissions.append({
                'id': sub['id'],
                'student_username': sub['student_id'],
                'student_grade': student_grade,
                'response': sub['response'],
                'grade': sub.get('grade'),
                'feedback': sub.get('feedback', ''),
                'submitted_at': sub['submitted_at']
            })
        
        # Sort by submission date
        prompt_submissions.sort(key=lambda x: x['submitted_at'], reverse=True)
        
        if not prompt_submissions:
            flash('No submissions found for this prompt yet.', 'info')
        
        return render_template('grade_submissions.html', 
                             prompt=prompt, 
                             submissions=prompt_submissions)
                             
    except Exception as e:
        logger.error(f"Grade submissions error: {e}")
        flash('Error loading submissions.', 'danger')
        return redirect(url_for('teacher_dashboard'))

@app.route('/teacher/students')
@teacher_required
def manage_students():
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('teacher_dashboard'))
    
    try:
        # Get all students
        users_response = supabase.table('users').select('*').eq('role', 'student').execute()
        students = users_response.data if users_response.data else []
        
        # Get submission counts for each student
        submissions_response = supabase.table('submissions').select('*').execute()
        submissions = submissions_response.data if submissions_response.data else []
        
        # Calculate student statistics
        student_stats = {}
        for student in students:
            student_subs = [s for s in submissions if s['student_id'] == student['username']]
            graded_subs = [s for s in student_subs if s.get('grade') is not None]
            
            student_stats[student['username']] = {
                'total_submissions': len(student_subs),
                'graded_submissions': len(graded_subs),
                'average_grade': sum(s['grade'] for s in graded_subs) / len(graded_subs) if graded_subs else 0
            }
        
        return render_template('manage_students.html', 
                             students=students, 
                             student_stats=student_stats)
                             
    except Exception as e:
        logger.error(f"Manage students error: {e}")
        flash('Error loading student management.', 'danger')
        return redirect(url_for('teacher_dashboard'))

@app.route('/teacher/delete_student/<username>', methods=['POST'])
@teacher_required
def delete_student(username):
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('manage_students'))
    
    try:
        # Get current user
        user_response = supabase.table('users').select('*').eq('username', session['user_id']).execute()
        current_user = user_response.data[0] if user_response.data else None
        
        if not current_user:
            flash('User not found.', 'danger')
            return redirect(url_for('manage_students'))
        
        # Get student to delete
        student_response = supabase.table('users').select('*').eq('username', username).execute()
        student = student_response.data[0] if student_response.data else None
        
        if not student:
            flash('Student not found.', 'warning')
            return redirect(url_for('manage_students'))
        
        # SIMPLIFIED PERMISSION CHECK:
        can_delete = False
        
        # 1. Super admin (sirius) can delete ANYONE
        if session['user_id'] == 'sirius':
            can_delete = True
        # 2. School admin can delete students in their school  
        elif (current_user.get('is_admin') and 
              current_user.get('school_id') == student.get('school_id')):
            can_delete = True
        # 3. Regular teachers can delete if same school (remove grade restriction)
        elif (current_user.get('school_id') == student.get('school_id')):
            can_delete = True
        
        if not can_delete:
            flash('Access denied. You can only delete students from your school.', 'danger')
            return redirect(url_for('manage_students'))
        
        # Delete student's submissions first
        submissions_result = supabase.table('submissions').delete().eq('student_id', username).execute()
        
        # Then delete the student user
        user_result = supabase.table('users').delete().eq('username', username).execute()
        
        if user_result.data:
            flash(f'Student {username} and their submissions have been deleted.', 'success')
        else:
            flash('Student not found or already deleted.', 'warning')
            
    except Exception as e:
        logger.error(f"Delete student error: {e}")
        flash('Error deleting student.', 'danger')
    
    return redirect(url_for('manage_students'))

@app.route('/fix-database')
def fix_database():
    """Debug and fix database schema issues"""
    supabase = get_supabase()
    if not supabase:
        return "Database connection failed"
    
    try:
        # Check schools table structure
        schools_response = supabase.table('schools').select('*').limit(1).execute()
        print("Schools table:", schools_response.data)
        
        # Check users table structure  
        users_response = supabase.table('users').select('*').limit(1).execute()
        print("Users table:", users_response.data)
        
        return f"""
        <h3>Database Check</h3>
        <p>Schools: {len(schools_response.data) if schools_response.data else 0} records</p>
        <p>Users: {len(users_response.data) if users_response.data else 0} records</p>
        <p>If you see errors above, you need to create the schools table in Supabase.</p>
        """
    except Exception as e:
        return f"Database error: {str(e)}"

@app.route('/student/dashboard')
@student_required
def student_dashboard():
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('logout'))
    
    try:
        # Handle Sirius differently
        if session['user_id'] == 'sirius':
            user = {
                'username': 'sirius', 
                'role': 'teacher', 
                'school_id': None, 
                'grade': '9',
                'id': 'school_demo_academy'
            }
        else:
            user = get_user_by_username(session['user_id'])
        
        if not user:
            flash("User not found. Please log in again.", "danger")
            return redirect(url_for('logout'))
        
        # Get all prompts for the student's school and grade
        if session['user_id'] == 'sirius':
            prompts_response = supabase.table('prompts').select('*').execute()
        else:
            prompts_response = supabase.table('prompts')\
                .select('*')\
                .eq('school_id', user['school_id'])\
                .eq('grade_level', user['grade'])\
                .execute()
        
        prompts = prompts_response.data if prompts_response.data else []
        
        # Get student's submissions
        if session['user_id'] == 'sirius':
            submissions_response = supabase.table('submissions').select('*').limit(50).execute()
        else:
            submissions_response = supabase.table('submissions')\
                .select('*')\
                .eq('student_id', user['username'])\
                .execute()
        
        submissions = submissions_response.data if submissions_response.data else []
        
        # Create a dictionary of prompt_id to submission for quick lookup
        submission_dict = {sub['prompt_id']: sub for sub in submissions}
        
        # Enhance prompts with submission info
        for prompt in prompts:
            prompt['has_submitted'] = prompt['id'] in submission_dict
            prompt['submission'] = submission_dict.get(prompt['id'])
        
        # Calculate statistics
        completed_assignments = len([p for p in prompts if p['has_submitted']])
        pending_assignments = len(prompts) - completed_assignments
        
        # Calculate average grade
        graded_submissions = [sub for sub in submissions if sub.get('grade') is not None]
        average_grade = round(sum(sub['grade'] for sub in graded_submissions) / len(graded_submissions), 1) if graded_submissions else 0
        
        # Calculate completion rate
        completion_rate = round((completed_assignments / len(prompts)) * 100, 1) if prompts else 0
        
        # Calculate subject averages
        subject_averages = {}
        for prompt in prompts:
            if prompt['has_submitted'] and prompt['submission'] and prompt['submission'].get('grade') is not None:
                subject = prompt.get('subject', 'General')
                if subject not in subject_averages:
                    subject_averages[subject] = []
                subject_averages[subject].append(prompt['submission']['grade'])
        
        # Calculate average for each subject
        for subject, grades in subject_averages.items():
            subject_averages[subject] = round(sum(grades) / len(grades), 1)
        
        # Get leaderboard rank
        if session['user_id'] == 'sirius':
            leaderboard_rank = 1
        else:
            all_students_response = supabase.table('users')\
                .select('username')\
                .eq('school_id', user['school_id'])\
                .eq('role', 'student')\
                .eq('grade', user['grade'])\
                .execute()
            
            leaderboard_rank = len(all_students_response.data) if all_students_response.data else 1
        
        # Get study materials count
        if session['user_id'] == 'sirius':
            materials_response = supabase.table('study_materials').select('id').execute()
        else:
            materials_response = supabase.table('study_materials')\
                .select('id')\
                .eq('school_id', user['school_id'])\
                .eq('grade_level', user['grade'])\
                .execute()
        
        materials_count = len(materials_response.data) if materials_response.data else 0

        # 🆕 NEW: Get Science Revision Stats
        science_stats = {
            'total_quizzes': 0,
            'average_score': 0,
            'best_score': 0,
            'recent_attempts': []
        }
        
        try:
            # Get quiz attempts for science revision
            attempts_response = supabase.table('student_quiz_attempts')\
                .select('*')\
                .eq('student_id', session['user_id'])\
                .order('completed_at', desc=True)\
                .limit(5)\
                .execute()
            
            if attempts_response.data:
                science_stats['total_quizzes'] = len(attempts_response.data)
                science_stats['recent_attempts'] = attempts_response.data[:3]  # Last 3 attempts
                
                # Calculate average score
                scores = [attempt['score'] for attempt in attempts_response.data if attempt['score'] is not None]
                if scores:
                    science_stats['average_score'] = round(sum(scores) / len(scores))
                    science_stats['best_score'] = max(scores)
        
        except Exception as e:
            logger.error(f"Science stats error: {e}")
            # Continue without science stats if there's an error

        return render_template(
            'student_dashboard.html',
            user=user,
            prompts=prompts,
            completed_assignments=completed_assignments,
            pending_assignments=pending_assignments,
            average_grade=average_grade,
            completion_rate=completion_rate,
            leaderboard_rank=leaderboard_rank,
            subject_averages=subject_averages,
            now=datetime.now(),
            materials_count=materials_count,
            science_stats=science_stats  # 🆕 NEW: Pass science stats to template
        )
        
    except Exception as e:
        logger.error(f"Student dashboard error: {e}")
        flash('Error loading dashboard.', 'danger')
        return redirect(url_for('logout'))


@app.route('/student/history')
@login_required
def student_history():
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('index'))
    
    try:
        # FIXED: Get current user using helper function
        user = get_user_by_username(session['user_id'])
        
        if not user or user['role'] != 'student':
            flash('Only students can view submission history.', 'warning')
            return redirect(url_for('teacher_dashboard'))
        
        # ... rest of the route remains the same ...
        
        # Get all submissions for this student with prompt info
        submissions_response = supabase.table('submissions').select('*').eq('student_id', session['user_id']).execute()
        student_submissions = []
        
        for sub in submissions_response.data:
            # Get prompt info
            prompt_response = supabase.table('prompts').select('*').eq('id', sub['prompt_id']).execute()
            prompt = prompt_response.data[0] if prompt_response.data else None
            
            if prompt:
                student_submissions.append({
                    'id': sub['id'],
                    'prompt_title': prompt['title'],
                    'prompt_description': prompt['description'],
                    'response': sub['response'],
                    'grade': sub.get('grade'),
                    'feedback': sub.get('feedback', ''),
                    'submitted_at': sub['submitted_at'],
                    'graded_at': sub.get('graded_at')
                })

        # Sort by submission date (most recent first)
        student_submissions.sort(key=lambda x: x['submitted_at'], reverse=True)
        
        # Calculate statistics
        total_submissions = len(student_submissions)
        graded_count = sum(1 for s in student_submissions if s['grade'] is not None)
        
        avg_grade = None
        if graded_count > 0:
            total_grade = sum(s['grade'] for s in student_submissions if s['grade'] is not None)
            avg_grade = round(total_grade / graded_count, 2)
        
        stats = {
            'total': total_submissions,
            'graded': graded_count,
            'pending': total_submissions - graded_count,
            'average': avg_grade
        }
        
        return render_template('student_history.html', 
                             submissions=student_submissions, 
                             stats=stats,
                             user=user)
                             
    except Exception as e:
        logger.error(f"Student history error: {e}")
        flash('Error loading submission history.', 'danger')
        return redirect(url_for('student_dashboard'))

@app.route('/student/submit/<prompt_id>', methods=['POST'])
@login_required
def submit_response(prompt_id):
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('student_dashboard'))
    
    try:
        # Get current user
        user_response = supabase.table('users').select('*').eq('username', session['user_id']).execute()
        user = user_response.data[0] if user_response.data else None
        
        if not user or user['role'] != 'student':
            flash('Access denied.', 'danger')
            return redirect(url_for('index'))
        
        response_text = request.form.get('response', '').strip()
        
        if not response_text:
            flash('Response cannot be empty.', 'danger')
            return redirect(url_for('student_dashboard'))
        
        # Check if already submitted
        existing_response = supabase.table('submissions').select('*').eq('prompt_id', prompt_id).eq('student_id', session['user_id']).execute()
        
        if existing_response.data:
            flash('You have already submitted a response to this prompt.', 'warning')
            return redirect(url_for('student_dashboard'))
        
        # Create submission
        submission_id = f"sub_{datetime.now().strftime('%Y%m%d%H%M%S')}_{session['user_id']}"
        submission_data = {
            'id': submission_id,
            'prompt_id': prompt_id,
            'student_id': session['user_id'],
            'response': response_text,
            'submitted_at': datetime.now().isoformat()
        }
        
        result = supabase.table('submissions').insert(submission_data).execute()
        
        if result.data:
            flash('Response submitted successfully!', 'success')
        else:
            flash('Failed to submit response.', 'danger')
            
    except Exception as e:
        logger.error(f"Submit response error: {e}")
        flash('Error submitting response.', 'danger')
    
    return redirect(url_for('student_dashboard'))

@app.route('/leaderboard')
@login_required
def leaderboard():
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('student_dashboard'))
    
    try:
        # Get grade filter from query parameter
        grade_filter = request.args.get('grade', 'all')
        
        # SCHOOL FILTER FOR SUPER ADMIN
        school_filter = request.args.get('school', 'all')
        if session.get('user_id') == 'sirius' and session.get('current_school_id'):
            school_filter = session['current_school_id']
        
        # Get all users with school filtering
        if school_filter != 'all' and school_filter:
            users_response = supabase.table('users').select('*').eq('school_id', school_filter).execute()
        else:
            users_response = supabase.table('users').select('*').execute()
            
        users_data = {user['username']: user for user in users_response.data} if users_response.data else {}
        
        # Get all prompts with school filtering
        if school_filter != 'all' and school_filter:
            prompts_response = supabase.table('prompts').select('*').eq('school_id', school_filter).execute()
        else:
            prompts_response = supabase.table('prompts').select('*').execute()
            
        prompts_data = prompts_response.data if prompts_response.data else []
        
        # Get all submissions with grades
        submissions_response = supabase.table('submissions').select('*').not_.is_('grade', 'null').execute()
        graded_submissions = submissions_response.data if submissions_response.data else []
        
        # Calculate average scores for each student - FAIR CALCULATION
        student_scores = {}
        
        for student_username, user_data in users_data.items():
            if user_data['role'] == 'student':
                student_grade = user_data['grade']
                
                # Get all prompts for this student's grade level and school
                if school_filter != 'all' and school_filter:
                    grade_prompts = [p for p in prompts_data if p['grade_level'] == student_grade and p['school_id'] == school_filter]
                else:
                    grade_prompts = [p for p in prompts_data if p['grade_level'] == student_grade]
                    
                total_prompts = len(grade_prompts)
                
                if total_prompts > 0:
                    # Initialize student data
                    student_scores[student_username] = {
                        'grades': [],  # Actual grades received
                        'possible_grades': [],  # Including zeros for missing submissions
                        'username': student_username,
                        'grade_level': student_grade,
                        'school_id': user_data.get('school_id'),
                        'total_prompts': total_prompts,
                        'submitted_prompts': 0
                    }
                    
                    # For each prompt in student's grade level
                    for prompt in grade_prompts:
                        # Find if student submitted to this prompt
                        submission = next((s for s in graded_submissions 
                                         if s['student_id'] == student_username 
                                         and s['prompt_id'] == prompt['id']), None)
                        
                        if submission:
                            # Student submitted and was graded
                            student_scores[student_username]['grades'].append(submission['grade'])
                            student_scores[student_username]['possible_grades'].append(submission['grade'])
                            student_scores[student_username]['submitted_prompts'] += 1
                        else:
                            # Student didn't submit - count as 0 for fair average
                            student_scores[student_username]['possible_grades'].append(0)
        
        # Calculate averages using FAIR calculation (include zeros for missing work)
        leaderboard_data = []
        for student_username, data in student_scores.items():
            if data['possible_grades']:  # Only include students with prompts in their grade
                # FAIR AVERAGE: sum of all grades (including zeros) / total prompts in grade
                fair_avg_score = sum(data['possible_grades']) / len(data['possible_grades'])
                
                leaderboard_data.append({
                    'username': data['username'],
                    'grade_level': data['grade_level'],
                    'school_id': data['school_id'],
                    'avg_score': round(fair_avg_score, 2),
                    'num_submissions': data['submitted_prompts'],
                    'total_prompts': data['total_prompts'],
                    'completion_rate': round((data['submitted_prompts'] / data['total_prompts']) * 100) if data['total_prompts'] > 0 else 0
                })
        
        # Apply grade filter if specified
        if grade_filter != 'all':
            leaderboard_data = [s for s in leaderboard_data if s['grade_level'] == grade_filter]
        
        # Apply school filter for display
        if school_filter != 'all' and school_filter:
            leaderboard_data = [s for s in leaderboard_data if s['school_id'] == school_filter]
        
        # Sort by average score (descending)
        leaderboard_data.sort(key=lambda x: x['avg_score'], reverse=True)
        
        # Add ranking
        for i, student in enumerate(leaderboard_data):
            student['rank'] = i + 1
        
        # Get unique grades for filter buttons
        unique_grades = sorted(list(set([s['grade_level'] for s in leaderboard_data])))
        
        # Get schools for super admin filter
        available_schools = []
        if session.get('user_id') == 'sirius':
            schools_response = supabase.table('schools').select('*').order('name').execute()
            available_schools = schools_response.data if schools_response.data else []
        
        return render_template('leaderboard.html', 
                             leaderboard=leaderboard_data,
                             current_grade_filter=grade_filter,
                             current_school_filter=school_filter,
                             available_grades=unique_grades,
                             available_schools=available_schools)
        
    except Exception as e:
        logger.error(f"Leaderboard error: {e}")
        flash('Error loading leaderboard.', 'danger')
        return redirect(url_for('student_dashboard'))

@app.route('/student/view_feedback/<submission_id>')
@login_required
def view_feedback(submission_id):
    """View feedback for a submission - enhanced for MCQ assessments"""
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('student_dashboard'))
    
    try:
        # Get submission
        submission_response = supabase.table('submissions').select('*').eq('id', submission_id).execute()
        submission = submission_response.data[0] if submission_response.data else None
        
        if not submission:
            flash('Submission not found.', 'danger')
            return redirect(url_for('student_dashboard'))
        
        # Check if this submission belongs to the current user
        if submission['student_id'] != session['user_id']:
            flash('Access denied.', 'danger')
            return redirect(url_for('student_dashboard'))
        
        # Get prompt details
        prompt_response = supabase.table('prompts').select('*').eq('id', submission['prompt_id']).execute()
        prompt = prompt_response.data[0] if prompt_response.data else None
        
        if not prompt:
            flash('Assessment not found.', 'danger')
            return redirect(url_for('student_dashboard'))

        # Get MCQ questions and responses if this was an MCQ/mixed assessment
        mcq_questions = []
        question_responses = []
        
        if prompt.get('assessment_type') in ['mcq', 'mixed']:
            # Get questions
            questions_response = supabase.table('mcq_questions').select('*').eq('prompt_id', prompt['id']).order('sort_order').execute()
            mcq_questions = questions_response.data if questions_response.data else []
            
            # Get student's responses
            responses_response = supabase.table('question_responses').select('*').eq('prompt_id', prompt['id']).eq('student_id', session['user_id']).execute()
            question_responses = responses_response.data if responses_response.data else []
        
        return render_template('view_feedback.html', 
                             submission=submission, 
                             prompt=prompt,
                             mcq_questions=mcq_questions,
                             question_responses=question_responses)
        
    except Exception as e:
        logger.error(f"View feedback error: {e}")
        flash('Error loading feedback.', 'danger')
        return redirect(url_for('student_dashboard'))
    
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        
        supabase = get_supabase()
        if not supabase:
            flash('Database connection error.', 'danger')
            return redirect(url_for('index'))
            
        try:
            # Get user from Supabase
            response = supabase.table('users').select('*').eq('username', session['user_id']).execute()
            user = response.data[0] if response.data else None
            
            if not user or not user.get('is_admin'):
                flash('Admin access required.', 'danger')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        except Exception as e:
            logger.error(f"Admin check error: {e}")
            flash('Error verifying admin permissions.', 'danger')
            return redirect(url_for('index'))
    return decorated_function

@app.route('/admin/dashboard')
@teacher_required
def admin_dashboard():
    """School-scoped admin dashboard for user approvals - FIXED FOR SIRIUS"""
    supabase = get_supabase()
    
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('index'))
    
    try:
        # FIXED: Get current user info using helper function
        user = get_user_by_username(session['user_id'])
        
        # DETERMINE SCHOOL CONTEXT
        school_id = None
        
        if session['user_id'] == 'sirius':
            # Sirius uses selected school context or shows all schools
            school_id = session.get('current_school_id')
            if not school_id:
                flash('Please select a school first using the school switcher.', 'warning')
                return redirect(url_for('super_admin_dashboard'))
        else:
            # Regular school admin uses their own school
            school_id = user.get('school_id') if user else None
        
        if not school_id:
            flash('School context required.', 'danger')
            return redirect(url_for('teacher_dashboard'))
        
        # ... rest of the route remains the same ...
        
        # Get pending registrations for the determined school
        pending_users = supabase.table('users').select('*').eq('approval_status', 'pending').eq('school_id', school_id).execute()
        
        # Get all users for the determined school
        all_users = supabase.table('users').select('*').eq('school_id', school_id).order('created_at', desc=True).execute()
        
        return render_template('admin_dashboard.html',
                             pending_users=pending_users.data if pending_users.data else [],
                             all_users=all_users.data if all_users.data else [])
    except Exception as e:
        logger.error(f"Admin dashboard error: {e}")
        flash('Error loading admin dashboard.', 'danger')
        return redirect(url_for('teacher_dashboard'))
    
    
@app.route('/admin/approve_user/<username>', methods=['POST'])
@admin_required
def approve_user(username):
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('admin_dashboard'))
    
    try:
        # Update user approval status to 'approved'
        result = supabase.table('users').update({'approval_status': 'approved'}).eq('username', username).execute()
        
        if result.data:
            flash(f'✅ User {username} has been approved successfully!', 'success')
        else:
            flash('User not found.', 'warning')
    except Exception as e:
        logger.error(f"Approve user error: {e}")
        flash('Error approving user.', 'danger')
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/reject_user/<username>', methods=['POST'])
@admin_required
def reject_user(username):
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('admin_dashboard'))
    
    try:
        # Update user approval status to 'rejected'
        result = supabase.table('users').update({'approval_status': 'rejected'}).eq('username', username).execute()
        
        if result.data:
            flash(f'❌ User {username} has been rejected.', 'success')
        else:
            flash('User not found.', 'warning')
    except Exception as e:
        logger.error(f"Reject user error: {e}")
        flash('Error rejecting user.', 'danger')
    
    return redirect(url_for('admin_dashboard'))

# Add this debug route BEFORE the final if __name__ block
@app.route('/debug-token/<username>')
def debug_token(username):
    supabase = get_supabase()
    if not supabase:
        return "No database connection"
    
    try:
        user_response = supabase.table('users').select('reset_token, reset_token_expiry, username').eq('username', username).execute()
        user = user_response.data[0] if user_response.data else None
        
        if user:
            return f"""
            <h3>Token Debug for: {user['username']}</h3>
            <p><strong>Reset Token:</strong> {user.get('reset_token', 'None')}</p>
            <p><strong>Token Expiry:</strong> {user.get('reset_token_expiry', 'None')}</p>
            <p><strong>Current Time:</strong> {datetime.now().isoformat()}</p>
            """
        else:
            return "User not found"
    except Exception as e:
        return f"Error: {e}"
    
@app.route('/verify-security', methods=['POST'])
def verify_security():
    username = request.form.get('username')
    
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('forgot_password'))
    
    try:
        user_response = supabase.table('users').select('*').eq('username', username).execute()
        user = user_response.data[0] if user_response.data else None
        
        if user and user.get('security_question'):
            # Store username in session for verification
            session['reset_username'] = username
            return render_template('security_question.html', 
                                question=user['security_question'],
                                username=username)
        else:
            flash('User not found or no security question set.', 'danger')
            return redirect(url_for('forgot_password'))
            
    except Exception as e:
        logger.error(f"Security question error: {e}")
        flash('Error verifying user.', 'danger')
        return redirect(url_for('forgot_password'))

@app.route('/reset-with-answer', methods=['POST'])
def reset_with_answer():
    answer = request.form.get('security_answer', '').strip().lower()
    username = session.get('reset_username')
    
    if not username:
        return redirect(url_for('forgot_password'))
    
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('forgot_password'))
    
    try:
        user_response = supabase.table('users').select('*').eq('username', username).execute()
        user = user_response.data[0] if user_response.data else None
        
        if user and check_password_hash(user['security_answer_hash'], answer):
            # Answer correct - generate reset token
            import secrets
            reset_token = secrets.token_urlsafe(32)
            supabase.table('users').update({
                'reset_token': reset_token,
                'reset_token_expiry': (datetime.now() + timedelta(hours=1)).isoformat()
            }).eq('username', username).execute()
            
            session.pop('reset_username', None)
            return redirect(url_for('reset_password', token=reset_token))
        else:
            flash('Incorrect security answer.', 'danger')
            return redirect(url_for('forgot_password'))
            
    except Exception as e:
        logger.error(f"Security answer error: {e}")
        flash('Error verifying answer.', 'danger')
        return redirect(url_for('forgot_password'))

@app.route('/get-hash/<password>')
def get_hash(password):
    return generate_password_hash(password)

@app.route('/school/register', methods=['GET', 'POST'])
def school_register():
    if request.method == 'POST':
        supabase = get_supabase()
        if not supabase:
            flash('Database connection error. Please try again.', 'danger')
            return render_template('school_register.html')
            
        school_name = request.form.get('school_name', '').strip()
        admin_username = request.form.get('admin_username', '').strip()
        admin_password = request.form.get('admin_password', '').strip()
        admin_email = request.form.get('admin_email', '').strip()
        contact_person = request.form.get('contact_person', '').strip()
        contact_phone = request.form.get('contact_phone', '').strip()
        
        # Validation
        if not all([school_name, admin_username, admin_password, admin_email]):
            flash('School name, admin username, password and email are required.', 'danger')
            return render_template('school_register.html')
        
        try:
            # Check if admin username already exists
            user_response = supabase.table('users').select('username').eq('username', admin_username).execute()
            if user_response.data:
                flash('Admin username already exists. Please choose another.', 'danger')
                return render_template('school_register.html')
            
            # Check if school name already exists
            school_response = supabase.table('schools').select('name').eq('name', school_name).execute()
            if school_response.data:
                flash('A school with this name already exists.', 'danger')
                return render_template('school_register.html')
            
            # Generate unique school ID
            import secrets
            school_id = f"school_{secrets.token_hex(8)}"
            
            # Create school with PENDING status
            school_data = {
                'id': school_id,
                'name': school_name,
                'status': 'pending',
                'contact_person': contact_person if contact_person else None,
                'contact_phone': contact_phone if contact_phone else None,
                'created_at': datetime.now().isoformat()
            }
            
            school_result = supabase.table('schools').insert(school_data).execute()
            
            if not school_result.data:
                flash('Failed to create school. Please try again.', 'danger')
                return render_template('school_register.html')
            
            # Create admin account (auto-approved for now, but school is pending)
            user_data = {
                'username': admin_username,
                'password_hash': generate_password_hash(admin_password),
                'email': admin_email,
                'role': 'teacher',
                'approval_status': 'approved',  # User is approved
                'school_id': school_id,
                'is_admin': True,  # Mark as school admin
                'created_at': datetime.now().isoformat()
            }
            
            user_result = supabase.table('users').insert(user_data).execute()
            
            if user_result.data:
                flash('School registration submitted successfully! Your school requires approval from the platform administrator. You will be notified once approved.', 'success')
                return redirect(url_for('index'))
            else:
                # Clean up school if user creation fails
                supabase.table('schools').delete().eq('id', school_id).execute()
                flash('Failed to create admin account. Please try again.', 'danger')
                
        except Exception as e:
            logger.error(f"School registration error: {e}")
            flash(f'Error during school registration: {str(e)}', 'danger')
    
    return render_template('school_register.html')

@app.route('/super/admin/schools')
@super_admin_required
def super_admin_schools():
    """Enhanced school management with user counts"""
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('index'))
    
    try:
        # Get all schools with user counts
        schools_response = supabase.table('schools').select('*').order('created_at', desc=True).execute()
        schools = schools_response.data if schools_response.data else []
        
        # Get user counts for each school - FIXED: use username instead of id
        schools_with_stats = []
        for school in schools:
            users_response = supabase.table('users').select('username').eq('school_id', school['id']).execute()
            user_count = len(users_response.data) if users_response.data else 0
            
            # Count by role - FIXED: use username instead of id
            teachers_response = supabase.table('users').select('username').eq('school_id', school['id']).eq('role', 'teacher').execute()
            students_response = supabase.table('users').select('username').eq('school_id', school['id']).eq('role', 'student').execute()
            
            school_with_stats = {
                **school,
                'total_users': user_count,
                'teacher_count': len(teachers_response.data) if teachers_response.data else 0,
                'student_count': len(students_response.data) if students_response.data else 0,
                'admin_user': None
            }
            
            # Find school admin
            admin_response = supabase.table('users').select('username').eq('school_id', school['id']).eq('is_admin', True).execute()
            if admin_response.data:
                school_with_stats['admin_user'] = admin_response.data[0]['username']
            
            schools_with_stats.append(school_with_stats)
        
        # Get stats
        pending_schools = [s for s in schools_with_stats if s['status'] == 'pending']
        active_schools = [s for s in schools_with_stats if s['status'] == 'active']
        
        stats = {
            'total_schools': len(schools_with_stats),
            'pending_schools': len(pending_schools),
            'active_schools': len(active_schools),
            'total_users': sum(s['total_users'] for s in schools_with_stats)
        }
        
        return render_template('super_admin_schools.html',
                             schools=schools_with_stats,
                             stats=stats)
                             
    except Exception as e:
        logger.error(f"Super admin schools error: {e}")
        flash('Error loading school management.', 'danger')
        return redirect(url_for('super_admin_dashboard'))

@app.route('/super/admin/school/<school_id>')
@super_admin_required
def super_admin_school_detail(school_id):
    """Detailed view of a specific school"""
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('super_admin_schools'))
    
    try:
        # Get school details
        school_response = supabase.table('schools').select('*').eq('id', school_id).execute()
        school = school_response.data[0] if school_response.data else None
        
        if not school:
            flash('School not found.', 'danger')
            return redirect(url_for('super_admin_schools'))
        
        # Get all users in school
        users_response = supabase.table('users').select('*').eq('school_id', school_id).order('created_at', desc=True).execute()
        users = users_response.data if users_response.data else []
        
        # Get school prompts and submissions
        prompts_response = supabase.table('prompts').select('*').eq('school_id', school_id).execute()
        prompts = prompts_response.data if prompts_response.data else []
        
        submissions_response = supabase.table('submissions').select('*').execute()
        all_submissions = submissions_response.data if submissions_response.data else []
        
        # Calculate school statistics
        teachers = [u for u in users if u['role'] == 'teacher']
        students = [u for u in users if u['role'] == 'student']
        pending_users = [u for u in users if u.get('approval_status') == 'pending']
        
        school_stats = {
            'total_users': len(users),
            'teachers': len(teachers),
            'students': len(students),
            'pending_approvals': len(pending_users),
            'total_prompts': len(prompts),
            'total_submissions': len(all_submissions),
            'active_teachers': len([t for t in teachers if t.get('approval_status') == 'approved']),
            'active_students': len([s for s in students if s.get('approval_status') == 'approved'])
        }
        
        return render_template('super_admin_school_detail.html',
                             school=school,
                             users=users,
                             stats=school_stats)
        
    except Exception as e:
        logger.error(f"School detail error: {e}")
        flash('Error loading school details.', 'danger')
        return redirect(url_for('super_admin_schools'))

@app.route('/super/admin/approve_school/<school_id>', methods=['POST'])
@super_admin_required
def approve_school(school_id):
    """Enhanced school approval with activation"""
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('super_admin_schools'))
    
    try:
        # Update school status to active
        school_result = supabase.table('schools').update({
            'status': 'active',
            'updated_at': datetime.now().isoformat()
        }).eq('id', school_id).execute()
        
        # Activate all users in the school
        user_result = supabase.table('users').update({
            'approval_status': 'approved'
        }).eq('school_id', school_id).execute()
        
        if school_result.data and user_result.data:
            # Get school name for notification
            school_response = supabase.table('schools').select('name').eq('id', school_id).execute()
            school_name = school_response.data[0]['name'] if school_response.data else 'Unknown School'
            
            flash(f'✅ School "{school_name}" approved successfully! All users have been activated.', 'success')
        else:
            flash('Error approving school.', 'danger')
            
    except Exception as e:
        logger.error(f"Approve school error: {e}")
        flash('Error approving school.', 'danger')
    
    return redirect(url_for('super_admin_schools'))

@app.route('/super/admin/reject_school/<school_id>', methods=['POST'])
@super_admin_required
def reject_school(school_id):
    """Enhanced school rejection with cleanup"""
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('super_admin_schools'))
    
    try:
        # Get school name before deletion
        school_response = supabase.table('schools').select('name').eq('id', school_id).execute()
        school_name = school_response.data[0]['name'] if school_response.data else 'Unknown School'
        
        # Delete all users in the school first
        supabase.table('users').delete().eq('school_id', school_id).execute()
        
        # Delete the school
        supabase.table('schools').delete().eq('id', school_id).execute()
        
        flash(f'❌ School "{school_name}" has been rejected and removed from the platform.', 'success')
            
    except Exception as e:
        logger.error(f"Reject school error: {e}")
        flash('Error rejecting school.', 'danger')
    
    return redirect(url_for('super_admin_schools'))

@app.route('/super/admin/reject_school/<school_id>', methods=['POST'])
@super_admin_required
def super_admin_reject_school(school_id):
    """Reject a pending school registration"""
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('super_admin_schools'))
    
    try:
        # Get school name before deletion
        school_response = supabase.table('schools').select('name').eq('id', school_id).execute()
        school_name = school_response.data[0]['name'] if school_response.data else 'Unknown School'
        
        # Delete all users in the school first
        supabase.table('users').delete().eq('school_id', school_id).execute()
        
        # Delete the school
        supabase.table('schools').delete().eq('id', school_id).execute()
        
        flash(f'❌ School registration "{school_name}" has been rejected and removed.', 'success')
            
    except Exception as e:
        logger.error(f"Reject school error: {e}")
        flash('Error rejecting school.', 'danger')
    
    return redirect(url_for('super_admin_schools'))


@app.route('/school/admin/dashboard')
@school_admin_required
def school_admin_dashboard():
    """Enhanced school admin dashboard with Sirius support + real statistics."""
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('index'))
    
    try:
        # -------------------------------------------------------
        # DETERMINE SCHOOL CONTEXT (SIRIUS VS REGULAR ADMIN)
        # -------------------------------------------------------
        school_id = None
        school = None

        # ----------------------------
        # SIRIUS SPECIAL HANDLING
        # ----------------------------
        if session["user_id"] == "sirius":
            school_id = session.get("current_school_id")
            if not school_id:
                flash("Please select a school first using the school switcher.", "warning")
                return redirect(url_for("super_admin_dashboard"))

            school_resp = (
                supabase.table("schools")
                .select("*")
                .eq("id", school_id)
                .execute()
            )
            school = school_resp.data[0] if school_resp.data else None

        # ----------------------------
        # REGULAR SCHOOL ADMIN
        # ----------------------------
        else:
            # FIXED: Use helper function
            user = get_user_by_username(session["user_id"])

            if not user or not user.get("is_admin"):
                flash("School admin access required.", "danger")
                return redirect(url_for("teacher_dashboard"))

            school_id = user["school_id"]

            school_resp = (
                supabase.table("schools")
                .select("*")
                .eq("id", school_id)
                .execute()
            )
            school = school_resp.data[0] if school_resp.data else None

        # If somehow no school exists
        if not school:
            flash("School not found.", "danger")
            return redirect(url_for("teacher_dashboard"))

        # -------------------------------------------------------
        # LOAD ALL SCHOOL DATA (WORKS FOR BOTH SIRIUS + REGULAR)
        # -------------------------------------------------------

        # Users
        users_resp = (
            supabase.table("users")
            .select("*")
            .eq("school_id", school_id)
            .execute()
        )
        school_users = users_resp.data or []

        # Prompts
        prompts_resp = (
            supabase.table("prompts")
            .select("*")
            .eq("school_id", school_id)
            .execute()
        )
        school_prompts = prompts_resp.data or []

        # Submissions (filtered by user role)
        subs_resp = supabase.table("submissions").select("*").execute()
        all_submissions = subs_resp.data or []

        # -------------------------------------------------------
        # METRICS + STATISTICS
        # -------------------------------------------------------
        teachers = [u for u in school_users if u["role"] == "teacher"]
        students = [u for u in school_users if u["role"] == "student"]
        pending_users = [u for u in school_users if u.get("approval_status") == "pending"]

        active_teachers = len([t for t in teachers if t.get("approval_status") == "approved"])
        teacher_admins = len([t for t in teachers if t.get("is_admin")])

        active_students = len([s for s in students if s.get("approval_status") == "approved"])

        written_assessments = len([p for p in school_prompts if p.get("assessment_type") == "written"])
        mcq_assessments = len([p for p in school_prompts if p.get("assessment_type") == "mcq"])
        mixed_assessments = len([p for p in school_prompts if p.get("assessment_type") == "mixed"])

        total_submissions = len(all_submissions)
        graded_submissions = len([s for s in all_submissions if s.get("grade") is not None])

        # Student completion calculations
        student_completion = {}
        for student in students:
            if student.get("approval_status") == "approved":
                student_subs = [s for s in all_submissions if s["student_id"] == student["username"]]
                student_prompts = [
                    p for p in school_prompts if p.get("grade_level") == student.get("grade")
                ]
                completion = (
                    (len(student_subs) / len(student_prompts)) * 100
                    if student_prompts else 0
                )
                student_completion[student["username"]] = completion

        avg_completion_rate = (
            round(sum(student_completion.values()) / len(student_completion))
            if student_completion
            else 0
        )

        stats = {
            "total_teachers": len(teachers),
            "active_teachers": active_teachers,
            "teacher_admins": teacher_admins,
            "total_students": len(students),
            "active_students": active_students,
            "pending_approvals": len(pending_users),
            "total_users": len(school_users),
            "total_assessments": len(school_prompts),
            "written_assessments": written_assessments,
            "mcq_assessments": mcq_assessments,
            "mixed_assessments": mixed_assessments,
            "total_submissions": total_submissions,
            "graded_submissions": graded_submissions,
            "avg_completion_rate": avg_completion_rate,
        }

        # Last 5 newly registered users
        recent_users = sorted(
            school_users, key=lambda x: x.get("created_at", "")
        , reverse=True)[:5]

        # Grade distribution
        grade_distribution = {}
        for student in students:
            if student.get("approval_status") == "approved":
                grade = student.get("grade", "Unknown")
                grade_distribution[grade] = grade_distribution.get(grade, 0) + 1

        # -------------------------------------------------------
        # RENDER TEMPLATE
        # -------------------------------------------------------
        return render_template(
            "school_admin_dashboard.html",
            school=school,
            users=school_users,
            stats=stats,
            recent_users=recent_users,
            grade_distribution=grade_distribution,
        )

    except Exception as e:
        logger.error(f"School admin dashboard error: {e}")
        flash("Error loading school admin dashboard.", "danger")
        return redirect(url_for("teacher_dashboard"))




@app.route('/school/admin/settings', methods=['GET', 'POST'])
@school_admin_required
def school_settings():
    """Enhanced school settings with better error handling"""
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('school_admin_dashboard'))
    
    try:
        # FIXED: Get current user and school using helper function
        user = get_user_by_username(session['user_id'])
        
        if not user or not user.get('is_admin'):
            flash('School admin access required.', 'danger')
            return redirect(url_for('teacher_dashboard'))
        
        # ... rest of the route remains the same ...

        if request.method == 'POST':
            school_name = request.form.get('school_name', '').strip()
            contact_person = request.form.get('contact_person', '').strip()
            contact_phone = request.form.get('contact_phone', '').strip()
            contact_email = request.form.get('contact_email', '').strip()
            
            if not school_name:
                flash('School name is required.', 'danger')
                return render_template('school_settings.html', school=school)
            
            # Check if school name already exists (excluding current school)
            if school_name != school['name']:
                existing_school = supabase.table('schools').select('name').eq('name', school_name).neq('id', school['id']).execute()
                if existing_school.data:
                    flash('A school with this name already exists.', 'danger')
                    return render_template('school_settings.html', school=school)
            
            # Update school info
            update_data = {
                'name': school_name,
                'contact_person': contact_person if contact_person else None,
                'contact_phone': contact_phone if contact_phone else None,
                'updated_at': datetime.now().isoformat()
            }
            
            # Only update contact_email if provided and different
            if contact_email and contact_email != user.get('email'):
                # Update admin user's email as well
                supabase.table('users').update({'email': contact_email}).eq('username', session['user_id']).execute()
            
            result = supabase.table('schools').update(update_data).eq('id', user['school_id']).execute()
            if result.data:
                flash('✅ School settings updated successfully!', 'success')
                # Refresh school data
                school_response = supabase.table('schools').select('*').eq('id', user['school_id']).execute()
                school = school_response.data[0] if school_response.data else None
            else:
                flash('Failed to update school settings.', 'danger')
        
        return render_template('school_settings.html', school=school, user=user)
        
    except Exception as e:
        logger.error(f"School settings error: {e}")
        flash('Error loading school settings.', 'danger')
        return redirect(url_for('school_admin_dashboard'))

@app.route('/super/admin')
@super_admin_required
def super_admin_dashboard():
    """Professional super admin dashboard - NO SCHOOL CONTEXT REQUIRED"""
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('index'))
    
    try:
        # Get all schools (school context NOT required for main dashboard)
        schools_response = supabase.table('schools').select('*').execute()
        schools = schools_response.data if schools_response.data else []
        
        # Get all users for platform stats
        users_response = supabase.table('users').select('*').execute()
        all_users = users_response.data if users_response.data else []
        
        # Calculate stats safely
        pending_schools = [s for s in schools if s.get('status') == 'pending']
        active_schools = [s for s in schools if s.get('status') == 'active']
        
        stats = {
            'total_schools': len(schools),
            'pending_schools': len(pending_schools),
            'active_schools': len(active_schools),
            'total_users': len(all_users),
            'active_sessions': 0,
            'storage_used': '0 GB'
        }
        
        # Get recent schools (last 5)
        recent_schools = sorted(schools, key=lambda x: x.get('created_at', ''), reverse=True)[:5]
        
        return render_template('super_admin_dashboard.html',
                             stats=stats,
                             recent_schools=recent_schools,
                             available_schools=schools)  # Pass schools for switcher
                             
    except Exception as e:
        logger.error(f"Super admin dashboard error: {e}")
        flash(f'Error loading dashboard: {str(e)}', 'danger')
        return render_template('super_admin_dashboard.html',
                             stats={'total_schools': 0, 'pending_schools': 0, 'active_schools': 0, 'total_users': 0, 'active_sessions': 0, 'storage_used': '0 GB'},
                             recent_schools=[],
                             available_schools=[])



@app.route('/super/admin/analytics')
@super_admin_required
def super_admin_analytics():
    """Platform-wide analytics for super admin"""
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('super_admin_dashboard'))
    
    try:
        # Platform statistics
        schools = supabase.table('schools').select('*').execute()
        users = supabase.table('users').select('*').execute()
        prompts = supabase.table('prompts').select('*').execute()
        submissions = supabase.table('submissions').select('*').execute()
        
        # Calculate platform stats
        active_schools = [s for s in schools.data if s.get('status') == 'active'] if schools.data else []
        pending_schools = [s for s in schools.data if s.get('status') == 'pending'] if schools.data else []
        
        teachers = [u for u in users.data if u.get('role') == 'teacher'] if users.data else []
        students = [u for u in users.data if u.get('role') == 'student'] if users.data else []
        
        stats = {
            'total_schools': len(schools.data) if schools.data else 0,
            'active_schools': len(active_schools),
            'pending_schools': len(pending_schools),
            'total_users': len(users.data) if users.data else 0,
            'teachers': len(teachers),
            'students': len(students),
            'total_prompts': len(prompts.data) if prompts.data else 0,
            'total_submissions': len(submissions.data) if submissions.data else 0,
        }
        
        return render_template('super_admin_analytics.html', stats=stats)
        
    except Exception as e:
        logger.error(f"Super admin analytics error: {e}")
        flash('Error loading analytics.', 'danger')
        return redirect(url_for('super_admin_dashboard'))
    
@app.route('/fix-admin-roles')
def fix_admin_roles():
    """Fix the admin role assignments"""
    supabase = get_supabase()
    if not supabase:
        return "Database connection failed"
    
    try:
        # Make newel_teacher the school admin
        result1 = supabase.table('users').update({'is_admin': True}).eq('username', 'newel_teacher').execute()
        
        # Ensure sirius has no school_id
        result2 = supabase.table('users').update({'school_id': None}).eq('username', 'sirius').execute()
        
        return """
        <h3>✅ Admin Roles Fixed!</h3>
        <p><strong>newel_teacher</strong> is now school admin</p>
        <p><strong>sirius</strong> is properly detached from schools</p>
        <a href="/debug-data" class="btn btn-primary">Check Database</a>
        """
    except Exception as e:
        return f"Error: {str(e)}"
    
@app.route('/student/assessment/<prompt_id>', methods=['GET', 'POST'])
@login_required
def take_assessment(prompt_id):
    """Student interface for taking assessments - UPDATED with percentage grading"""
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('student_dashboard'))
    
    try:
        # Get current user
        user_response = supabase.table('users').select('*').eq('username', session['user_id']).execute()
        user = user_response.data[0] if user_response.data else None
        
        if not user or user['role'] != 'student':
            flash('Access denied.', 'danger')
            return redirect(url_for('index'))

        # Get prompt details
        prompt_response = supabase.table('prompts').select('*').eq('id', prompt_id).execute()
        prompt = prompt_response.data[0] if prompt_response.data else None
        
        if not prompt:
            flash('Assessment not found.', 'danger')
            return redirect(url_for('student_dashboard'))

        # Check if already submitted
        existing_response = supabase.table('submissions').select('*').eq('prompt_id', prompt_id).eq('student_id', session['user_id']).execute()
        if existing_response.data:
            flash('You have already submitted this assessment.', 'warning')
            return redirect(url_for('student_dashboard'))

        # Get MCQ questions if applicable
        questions = []
        if prompt.get('assessment_type') in ['mcq', 'mixed']:
            questions_response = supabase.table('mcq_questions').select('*').eq('prompt_id', prompt_id).order('sort_order').execute()
            questions = questions_response.data if questions_response.data else []

        if request.method == 'POST':
            written_response = request.form.get('written_response', '').strip()
            
            # Validate written response for written/mixed assessments
            if prompt.get('assessment_type') in ['written', 'mixed'] and not written_response:
                flash('Written response is required.', 'danger')
                return render_template('take_assessment.html', prompt=prompt, questions=questions, user=user)

            # Create submission
            submission_id = f"sub_{datetime.now().strftime('%Y%m%d%H%M%S')}_{session['user_id']}"
            submission_data = {
                'id': submission_id,
                'prompt_id': prompt_id,
                'student_id': session['user_id'],
                'response': written_response,
                'submitted_at': datetime.now().isoformat()
            }

            # Insert submission
            submission_result = supabase.table('submissions').insert(submission_data).execute()
            
            if not submission_result.data:
                flash('Failed to submit assessment.', 'danger')
                return render_template('take_assessment.html', prompt=prompt, questions=questions, user=user)

            # Handle MCQ responses - UPDATED WITH PERCENTAGE GRADING
            if prompt.get('assessment_type') in ['mcq', 'mixed'] and questions:
                question_responses = []
                correct_answers = 0
                total_questions = len(questions)
                
                for question in questions:
                    response_key = f"question_{question['id']}"
                    student_answer = request.form.get(response_key, '').strip()
                    
                    if student_answer:
                        # Auto-grade MCQ and True/False questions
                        is_correct = False
                        auto_graded = False
                        points_earned = 0
                        
                        if question['question_type'] in ['mcq', 'true_false']:
                            auto_graded = True
                            is_correct = (student_answer == question['correct_answer'])
                            if is_correct:
                                correct_answers += 1
                        
                        response_data = {
                            'id': f"resp_{question['id']}_{session['user_id']}",
                            'question_id': question['id'],
                            'student_id': session['user_id'],
                            'prompt_id': prompt_id,
                            'response_text': student_answer,
                            'is_correct': is_correct,
                            'auto_graded': auto_graded,
                            'points_earned': points_earned,
                            'submitted_at': datetime.now().isoformat()
                        }
                        question_responses.append(response_data)
                
                if question_responses:
                    supabase.table('question_responses').insert(question_responses).execute()
                    
                    # Calculate percentage score for MCQ-only assessments - UPDATED
                    if prompt.get('assessment_type') == 'mcq' and total_questions > 0:
                        percentage_score = (correct_answers / total_questions) * 100
                        supabase.table('submissions').update({
                            'grade': round(percentage_score, 2),
                            'graded_at': datetime.now().isoformat()
                        }).eq('id', submission_id).execute()

            flash('Assessment submitted successfully!', 'success')
            return redirect(url_for('student_dashboard'))

        return render_template('take_assessment.html', prompt=prompt, questions=questions, user=user)
        
    except Exception as e:
        logger.error(f"Take assessment error: {e}")
        flash('Error loading assessment.', 'danger')
        return redirect(url_for('student_dashboard'))
    
@app.route('/migrate-teacher-permissions')
@super_admin_required
def migrate_teacher_permissions():
    """Add teacher_permissions field to users table"""
    supabase = get_supabase()
    if not supabase:
        return "Database connection failed"
    
    try:
        # Check if teacher_permissions column exists
        test_user = supabase.table('users').select('username').limit(1).execute()
        if test_user.data:
            user_columns = list(test_user.data[0].keys())
            
            if 'teacher_permissions' in user_columns:
                return """
                <h3>✅ Teacher Permissions Column Already Exists</h3>
                <p>The <code>teacher_permissions</code> column is already in the users table.</p>
                <p>Current columns: <pre>{}</pre></p>
                <a href="/debug-data" class="btn btn-primary">Check Database</a>
                """.format(user_columns)
        
        # Column doesn't exist - provide SQL to run
        return """
        <h3>📋 Database Migration Required</h3>
        <p>You need to add the <code>teacher_permissions</code> column to your users table.</p>
        
        <p>Go to <strong>Supabase → SQL Editor</strong> and run this SQL:</p>
        
        <pre>
-- Add teacher_permissions column
ALTER TABLE users ADD COLUMN IF NOT EXISTS teacher_permissions TEXT DEFAULT 'classroom';

-- Update existing teachers: school admins keep admin, others become classroom teachers
UPDATE users 
SET teacher_permissions = CASE 
    WHEN is_admin = true THEN 'admin' 
    ELSE 'classroom' 
END
WHERE role = 'teacher';

-- Verify the update
SELECT username, role, is_admin, teacher_permissions 
FROM users 
WHERE role = 'teacher';
        </pre>
        
        <p>After running the SQL, <a href="/migrate-teacher-permissions">refresh this page</a> to verify.</p>
        """
                
    except Exception as e:
        error_msg = str(e)
        if 'teacher_permissions' in error_msg:
            return """
            <h3>❌ Missing teacher_permissions Column</h3>
            <p>The SQL above needs to be executed in Supabase.</p>
            <p>Error: {}</p>
            """.format(error_msg)
        return f"Error checking database: {error_msg}"

@app.route('/verify-teacher-roles')
@super_admin_required
def verify_teacher_roles():
    """Verify teacher permissions are set correctly"""
    supabase = get_supabase()
    if not supabase:
        return "Database connection failed"
    
    try:
        # Get all teachers with their permissions
        teachers_response = supabase.table('users').select('username, role, is_admin, teacher_permissions').eq('role', 'teacher').execute()
        teachers = teachers_response.data if teachers_response.data else []
        
        html = """
        <h3>👨‍🏫 Teacher Permissions Verification</h3>
        <table class="table table-striped">
            <thead>
                <tr>
                    <th>Username</th>
                    <th>Is Admin</th>
                    <th>Teacher Permissions</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
        """
        
        for teacher in teachers:
            status = "✅ OK" if teacher.get('teacher_permissions') else "❌ Missing"
            html += f"""
                <tr>
                    <td>{teacher['username']}</td>
                    <td>{'✅' if teacher.get('is_admin') else '❌'}</td>
                    <td>{teacher.get('teacher_permissions', 'MISSING')}</td>
                    <td>{status}</td>
                </tr>
            """
        
        html += """
            </tbody>
        </table>
        <a href="/migrate-teacher-permissions" class="btn btn-primary">Run Migration</a>
        <a href="/debug-data" class="btn btn-secondary">Database Debug</a>
        """
        
        return html
        
    except Exception as e:
        return f"Error: {str(e)}"
    

@app.route('/switch-school/<school_id>')
@super_admin_required
def switch_school(school_id):
    """Allow sirius to switch between school contexts"""
    if school_id == 'none':
        session.pop('current_school_id', None)
        session.pop('current_teacher_id', None)
        flash('Switched to platform admin view.', 'info')
        return redirect(url_for('super_admin_dashboard'))
    else:
        # Verify school exists
        supabase = get_supabase()
        if supabase:
            school_response = supabase.table('schools').select('name').eq('id', school_id).execute()
            if school_response.data:
                session['current_school_id'] = school_id
                session.pop('current_teacher_id', None)  # Clear teacher context
                flash(f'Switched to {school_response.data[0]["name"]} view.', 'info')
                # REDIRECT TO SCHOOL DASHBOARD instead of referrer
                return redirect(url_for('school_admin_dashboard'))
            else:
                flash('School not found.', 'danger')
        
        return redirect(url_for('super_admin_dashboard'))

@app.route('/switch-teacher/<teacher_id>')
@login_required
def switch_teacher(teacher_id):
    """Switch teacher context for school admins and super admin"""
    if teacher_id == 'none':
        session.pop('current_teacher_id', None)
        flash('Switched to school admin view.', 'info')
    else:
        # Verify teacher exists and has permission
        supabase = get_supabase()
        if supabase:
            # For school admins, ensure teacher is in their school
            if session['user_id'] != 'sirius':
                user_response = supabase.table('users').select('school_id').eq('username', session['user_id']).execute()
                user_school = user_response.data[0]['school_id'] if user_response.data else None
                
                teacher_response = supabase.table('users').select('username, school_id').eq('username', teacher_id).eq('role', 'teacher').execute()
                teacher = teacher_response.data[0] if teacher_response.data else None
                
                if teacher and teacher['school_id'] == user_school:
                    session['current_teacher_id'] = teacher_id
                    flash(f'Switched to {teacher_id} view.', 'info')
                else:
                    flash('Teacher not found in your school.', 'danger')
            else:
                # Super admin can switch to any teacher
                teacher_response = supabase.table('users').select('username').eq('username', teacher_id).eq('role', 'teacher').execute()
                if teacher_response.data:
                    session['current_teacher_id'] = teacher_id
                    flash(f'Switched to {teacher_id} view.', 'info')
                else:
                    flash('Teacher not found.', 'danger')
    
    return redirect(request.referrer or url_for('teacher_dashboard'))



@app.route('/school/admin/analytics')
@school_admin_required
def school_admin_analytics():
    """School-wide analytics dashboard"""
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('school_admin_dashboard'))
    
    try:
        # Get current user and school
        user_response = supabase.table('users').select('*').eq('username', session['user_id']).execute()
        user = user_response.data[0] if user_response.data else None
        
        if not user or not user.get('is_admin'):
            flash('School admin access required.', 'danger')
            return redirect(url_for('teacher_dashboard'))
        
        school_id = user['school_id']
        
        # Get comprehensive school data
        # 1. Student and teacher counts
        users_response = supabase.table('users').select('*').eq('school_id', school_id).execute()
        school_users = users_response.data if users_response.data else []
        
        # 2. All prompts and submissions
        prompts_response = supabase.table('prompts').select('*').eq('school_id', school_id).execute()
        school_prompts = prompts_response.data if prompts_response.data else []
        
        submissions_response = supabase.table('submissions').select('*').execute()
        all_submissions = submissions_response.data if submissions_response.data else []
        
        # CALCULATE ANALYTICS
        
        # User Statistics
        teachers = [u for u in school_users if u['role'] == 'teacher']
        students = [u for u in school_users if u['role'] == 'student']
        active_teachers = len([t for t in teachers if t.get('approval_status') == 'approved'])
        active_students = len([s for s in students if s.get('approval_status') == 'approved'])
        
        # Assessment Statistics
        written_assessments = len([p for p in school_prompts if p.get('assessment_type') == 'written'])
        mcq_assessments = len([p for p in school_prompts if p.get('assessment_type') == 'mcq'])
        mixed_assessments = len([p for p in school_prompts if p.get('assessment_type') == 'mixed'])
        
        # Submission Statistics
        total_submissions = len([s for s in all_submissions if any(p['id'] == s['prompt_id'] for p in school_prompts)])
        graded_submissions = len([s for s in all_submissions if s.get('grade') is not None and any(p['id'] == s['prompt_id'] for p in school_prompts)])
        
        # Grade Distribution
        grade_distribution = {}
        for student in students:
            if student.get('approval_status') == 'approved':
                grade = student.get('grade', 'Unknown')
                grade_distribution[grade] = grade_distribution.get(grade, 0) + 1
        
        # Subject Performance
        subject_performance = {}
        for prompt in school_prompts:
            subject = prompt.get('subject', 'general')
            if subject not in subject_performance:
                subject_performance[subject] = {'prompts': 0, 'submissions': 0, 'total_grade': 0, 'count': 0}
            subject_performance[subject]['prompts'] += 1
            
            # Calculate average grade for this subject
            prompt_submissions = [s for s in all_submissions if s['prompt_id'] == prompt['id'] and s.get('grade') is not None]
            for sub in prompt_submissions:
                subject_performance[subject]['submissions'] += 1
                subject_performance[subject]['total_grade'] += sub['grade']
                subject_performance[subject]['count'] += 1
        
        # Calculate subject averages
        for subject, data in subject_performance.items():
            if data['count'] > 0:
                data['average_grade'] = round(data['total_grade'] / data['count'], 1)
            else:
                data['average_grade'] = 0
        
        # Teacher Activity
        teacher_activity = {}
        for teacher in teachers:
            if teacher.get('approval_status') == 'approved':
                teacher_prompts = [p for p in school_prompts if p['created_by'] == teacher['username']]
                teacher_activity[teacher['username']] = {
                    'prompts_created': len(teacher_prompts),
                    'total_points': sum(p.get('total_points', 0) for p in teacher_prompts),
                    'submissions_count': len([s for s in all_submissions if any(p['id'] == s['prompt_id'] for p in teacher_prompts)])
                }
        
        # Student Performance by Grade
        grade_performance = {}
        for student in students:
            if student.get('approval_status') == 'approved':
                grade = student.get('grade', 'Unknown')
                if grade not in grade_performance:
                    grade_performance[grade] = {'students': 0, 'total_grade': 0, 'submission_count': 0}
                
                grade_performance[grade]['students'] += 1
                student_subs = [s for s in all_submissions if s['student_id'] == student['username'] and s.get('grade') is not None]
                for sub in student_subs:
                    grade_performance[grade]['total_grade'] += sub['grade']
                    grade_performance[grade]['submission_count'] += 1
        
        # Calculate grade averages
        for grade, data in grade_performance.items():
            if data['submission_count'] > 0:
                data['average_grade'] = round(data['total_grade'] / data['submission_count'], 1)
            else:
                data['average_grade'] = 0
        
        analytics_data = {
            'user_stats': {
                'total_teachers': len(teachers),
                'active_teachers': active_teachers,
                'total_students': len(students),
                'active_students': active_students,
                'teacher_admins': len([t for t in teachers if t.get('teacher_permissions') == 'admin'])
            },
            'assessment_stats': {
                'total_assessments': len(school_prompts),
                'written_assessments': written_assessments,
                'mcq_assessments': mcq_assessments,
                'mixed_assessments': mixed_assessments,
                'total_submissions': total_submissions,
                'graded_submissions': graded_submissions,
                'completion_rate': round((total_submissions / (len(school_prompts) * active_students)) * 100, 1) if active_students > 0 else 0
            },
            'grade_distribution': grade_distribution,
            'subject_performance': subject_performance,
            'teacher_activity': teacher_activity,
            'grade_performance': grade_performance
        }
        
        return render_template('school_analytics.html',
                             analytics=analytics_data,
                             school_id=school_id)
                             
    except Exception as e:
        logger.error(f"School analytics error: {e}")
        flash('Error loading analytics dashboard.', 'danger')
        return redirect(url_for('school_admin_dashboard'))

@app.route('/super/admin/delete_user/<username>', methods=['POST'])
@super_admin_required
def super_admin_delete_user(username):
    """Super admin delete ANY user"""
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('super_admin_users'))
    
    try:
        # Delete user's submissions first
        supabase.table('submissions').delete().eq('student_id', username).execute()
        
        # Delete user's question responses
        supabase.table('question_responses').delete().eq('student_id', username).execute()
        
        # Delete prompts created by this user
        supabase.table('prompts').delete().eq('created_by', username).execute()
        
        # Finally delete the user
        user_result = supabase.table('users').delete().eq('username', username).execute()
        
        if user_result.data:
            flash(f'✅ User {username} and all their data have been permanently deleted.', 'success')
        else:
            flash('User not found or already deleted.', 'warning')
            
    except Exception as e:
        logger.error(f"Super admin delete user error: {e}")
        flash('Error deleting user.', 'danger')
    
    return redirect(url_for('super_admin_users'))

@app.route('/super/admin/edit_user/<username>', methods=['GET', 'POST'])
@super_admin_required
def super_admin_edit_user(username):
    """Super admin edit ANY user"""
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('super_admin_users'))
    
    try:
        # Get user to edit
        user_response = supabase.table('users').select('*, schools(name)').eq('username', username).execute()
        user = user_response.data[0] if user_response.data else None
        
        if not user:
            flash('User not found.', 'danger')
            return redirect(url_for('super_admin_users'))
        
        if request.method == 'POST':
            # Get form data
            new_role = request.form.get('role')
            new_school_id = request.form.get('school_id')
            is_admin = request.form.get('is_admin') == 'on'
            approval_status = request.form.get('approval_status')
            teacher_permissions = request.form.get('teacher_permissions', 'classroom')
            
            # Update user
            update_data = {
                'role': new_role,
                'school_id': new_school_id,
                'is_admin': is_admin,
                'approval_status': approval_status,
                'teacher_permissions': teacher_permissions
            }
            
            result = supabase.table('users').update(update_data).eq('username', username).execute()
            
            if result.data:
                flash(f'✅ User {username} updated successfully!', 'success')
                return redirect(url_for('super_admin_users'))
            else:
                flash('Failed to update user.', 'danger')
        
        # Get all schools for dropdown
        schools_response = supabase.table('schools').select('*').order('name').execute()
        schools = schools_response.data if schools_response.data else []
        
        return render_template('super_admin_edit_user.html', 
                             user=user, 
                             schools=schools)
                             
    except Exception as e:
        logger.error(f"Super admin edit user error: {e}")
        flash('Error editing user.', 'danger')
        return redirect(url_for('super_admin_users'))

@app.route('/super/admin/impersonate/<username>')
@super_admin_required
def super_admin_impersonate(username):
    """Super admin impersonate any user"""
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('super_admin_users'))
    
    try:
        # Get user to impersonate
        user_response = supabase.table('users').select('*').eq('username', username).execute()
        user = user_response.data[0] if user_response.data else None
        
        if not user:
            flash('User not found.', 'danger')
            return redirect(url_for('super_admin_users'))
        
        # Store original admin session
        session['original_admin'] = session['user_id']
        
        # Impersonate the user
        session['user_id'] = user['username']
        session['role'] = user['role']
        
        flash(f'🔓 Now impersonating {username}. Use the "Return to Admin" button to switch back.', 'warning')
        
        # Redirect based on role
        if user['role'] == 'teacher':
            return redirect(url_for('teacher_dashboard'))
        else:
            return redirect(url_for('student_dashboard'))
            
    except Exception as e:
        logger.error(f"Impersonation error: {e}")
        flash('Error impersonating user.', 'danger')
        return redirect(url_for('super_admin_users'))

@app.route('/super/admin/return')
def super_admin_return():
    """Return to original admin session after impersonation"""
    if 'original_admin' in session:
        original_admin = session['original_admin']
        session['user_id'] = original_admin
        session['role'] = 'teacher'  # Sirius is always teacher role
        session.pop('original_admin', None)
        flash('🔐 Returned to super admin session.', 'success')
        return redirect(url_for('super_admin_dashboard'))
    else:
        flash('No impersonation session found.', 'warning')
        return redirect(url_for('super_admin_dashboard'))

@app.route('/teacher/student_records')
@teacher_required
def student_records():
    """Comprehensive student assessment records"""
    supabase = get_supabase()
    
    # Get current user's school context
    user_response = supabase.table('users').select('school_id').eq('username', session['user_id']).execute()
    school_id = user_response.data[0]['school_id'] if user_response.data else None
    
    # Get all students in school with their submissions
    students_response = supabase.table('users').select('*').eq('school_id', school_id).eq('role', 'student').execute()
    students = students_response.data if students_response.data else []
    
    student_records = {}
    for student in students:
        # Get all submissions with prompt details
        submissions_response = supabase.table('submissions')\
            .select('*, prompts(title, subject, assessment_type, total_points, grade_level)')\
            .eq('student_id', student['username'])\
            .execute()
        
        submissions = submissions_response.data if submissions_response.data else []
        
        # Calculate cumulative stats
        graded_submissions = [s for s in submissions if s.get('grade') is not None]
        total_points = sum(s.get('grade', 0) for s in graded_submissions)
        average_grade = total_points / len(graded_submissions) if graded_submissions else 0
        
        student_records[student['username']] = {
            'student': student,
            'submissions': submissions,
            'total_assessments': len(submissions),
            'graded_assessments': len(graded_submissions),
            'average_grade': round(average_grade, 2),
            'subjects': {}
        }
        
        # Group by subject
        for submission in submissions:
            subject = submission['prompts']['subject'] if submission['prompts'] else 'general'
            if subject not in student_records[student['username']]['subjects']:
                student_records[student['username']]['subjects'][subject] = {
                    'assessments': 0,
                    'average': 0,
                    'grades': []
                }
            
            if submission.get('grade') is not None:
                student_records[student['username']]['subjects'][subject]['grades'].append(submission['grade'])
                student_records[student['username']]['subjects'][subject]['assessments'] += 1
                student_records[student['username']]['subjects'][subject]['average'] = \
                    sum(student_records[student['username']]['subjects'][subject]['grades']) / \
                    len(student_records[student['username']]['subjects'][subject]['grades'])
    
    return render_template('student_records.html', 
                         student_records=student_records,
                         school_id=school_id)

@app.route('/super/admin/users')
@super_admin_required
def super_admin_users():
    """Super admin management of ALL users"""
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('super_admin_dashboard'))
    
    try:
        # Get ALL users across all schools
        users_response = supabase.table('users').select('*, schools(name)').order('created_at', desc=True).execute()
        all_users = users_response.data if users_response.data else []
        
        # Get all schools for filtering
        schools_response = supabase.table('schools').select('*').order('name').execute()
        schools = schools_response.data if schools_response.data else []
        
        return render_template('super_admin_users.html',
                             users=all_users,
                             schools=schools)
                             
    except Exception as e:
        logger.error(f"Super admin users error: {e}")
        flash('Error loading user management.', 'danger')
        return redirect(url_for('super_admin_dashboard'))



@app.route('/super/admin/fix-teacher-school', methods=['POST'])
@super_admin_required
def fix_teacher_school():
    """Fix teacher school assignment"""
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('super_admin_users'))
    
    try:
        username = request.form.get('username')
        new_school_id = request.form.get('school_id')
        
        if not username or not new_school_id:
            flash('Username and school are required.', 'danger')
            return redirect(url_for('super_admin_users'))
        
        # Update teacher's school
        result = supabase.table('users').update({
            'school_id': new_school_id
        }).eq('username', username).execute()
        
        if result.data:
            flash(f'✅ Teacher {username} moved to new school successfully!', 'success')
        else:
            flash('Teacher not found.', 'warning')
            
    except Exception as e:
        logger.error(f"Fix teacher school error: {e}")
        flash('Error updating teacher school.', 'danger')
    
    return redirect(url_for('super_admin_users'))

@app.route('/super/admin/delete_school/<school_id>', methods=['POST'])
@super_admin_required
def super_admin_delete_school(school_id):
    """Delete an active school and all its data"""
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('super_admin_schools'))
    
    try:
        # Get school name before deletion
        school_response = supabase.table('schools').select('name').eq('id', school_id).execute()
        school_name = school_response.data[0]['name'] if school_response.data else 'Unknown School'
        
        # Delete all data in this order to respect foreign key constraints:
        
        # 1. Delete question responses (if table exists)
        try:
            supabase.table('question_responses').delete().eq('prompt_id', school_id).execute()
        except:
            pass  # Table might not exist
        
        # 2. Delete MCQ questions (if table exists)
        try:
            supabase.table('mcq_questions').delete().eq('prompt_id', school_id).execute()
        except:
            pass  # Table might not exist
        
        # 3. Delete submissions
        supabase.table('submissions').delete().eq('prompt_id', school_id).execute()
        
        # 4. Delete prompts
        supabase.table('prompts').delete().eq('school_id', school_id).execute()
        
        # 5. Delete users
        supabase.table('users').delete().eq('school_id', school_id).execute()
        
        # 6. Finally delete the school
        supabase.table('schools').delete().eq('id', school_id).execute()
        
        flash(f'✅ School "{school_name}" and all its data have been permanently deleted.', 'success')
            
    except Exception as e:
        logger.error(f"Delete school error: {e}")
        flash('Error deleting school. Please try again.', 'danger')
    
    return redirect(url_for('super_admin_schools'))

@app.route('/teacher/materials')
@teacher_required
def teacher_materials():
    """Teacher's study materials management"""
    supabase = get_supabase()
    user_response = supabase.table('users').select('school_id').eq('username', session['user_id']).execute()
    school_id = user_response.data[0]['school_id'] if user_response.data else None
    
    materials_response = supabase.table('study_materials').select('*').eq('school_id', school_id).order('created_at', desc=True).execute()
    materials = materials_response.data if materials_response.data else []
    
    return render_template('teacher_materials.html', materials=materials)

@app.route('/teacher/upload_material', methods=['GET', 'POST'])
@teacher_required
def upload_material():
    """Upload study materials with fixed database schema"""
    if request.method == 'POST':
        supabase = get_supabase()
        
        # Get form data
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        material_type = request.form.get('material_type')
        subject = request.form.get('subject')
        grade_level = request.form.get('grade_level')
        tags = [tag.strip() for tag in request.form.get('tags', '').split(',') if tag.strip()]
        
        # Get user and school info
        user_response = supabase.table('users').select('school_id').eq('username', session['user_id']).execute()
        school_id = user_response.data[0]['school_id'] if user_response.data else None
        
        # Handle different material types
        file_url = None
        video_url = None
        web_url = None
        content_text = None
        original_filename = None  # Store original filename separately
        
        if material_type == 'file':
            file = request.files.get('file')
            if file and allowed_file(file.filename):
                if not validate_file_size(file):
                    flash('File too large. Maximum size is 16MB.', 'danger')
                    return render_template('upload_material.html')
                
                # Generate secure filename
                original_filename = secure_filename(file.filename)
                file_path = os.path.join(UPLOAD_FOLDER, original_filename)
                file.save(file_path)

                # Store URL that points to your download route
                file_url = f"/download/{original_filename}"
                
                # Store basic content text (for AI explanation)
                content_text = f"File: {original_filename} (uploaded successfully)"
            else:
                flash('Invalid file type.', 'danger')
                return render_template('upload_material.html')
        
        elif material_type == 'video':
            video_url = request.form.get('video_url', '').strip()
        
        elif material_type == 'web':
            web_url = request.form.get('web_url', '').strip()
        
        elif material_type == 'text':
            content_text = request.form.get('content_text', '').strip()
        
        # Create material record - FIXED: Don't include filename if column doesn't exist
        material_id = f"material_{uuid.uuid4().hex[:12]}"
        material_data = {
            'id': material_id,
            'title': title,
            'description': description,
            'material_type': material_type,
            'subject': subject,
            'grade_level': grade_level,
            'created_by': session['user_id'],
            'school_id': school_id,
            'tags': tags,
            'file_url': file_url,
            'video_url': video_url,
            'web_url': web_url,
            'content_text': content_text,
            # 🎯 REMOVED: 'filename': original_filename,  # Column doesn't exist
            'created_at': datetime.now().isoformat()
        }
        
        result = supabase.table('study_materials').insert(material_data).execute()
        
        if result.data:
            flash('Study material uploaded successfully!', 'success')
            return redirect(url_for('teacher_materials'))
        else:
            flash('Error uploading material.', 'danger')
    
    return render_template('upload_material.html')


@app.route('/student/materials')
@student_required
def student_materials():
    """Student view of study materials - FIXED VERSION with error handling"""
    supabase = get_supabase()
    if not supabase:
        flash('Database connection error.', 'danger')
        return redirect(url_for('student_dashboard'))
    
    try:
        # Handle Sirius differently
        if session['user_id'] == 'sirius':
            # Sirius can view any materials - use selected school context
            user_data = {
                'school_id': session.get('current_school_id'),
                'grade': '9'  # Default grade for demo
            }
            if not user_data['school_id']:
                flash('Please select a school first using the school switcher.', 'warning')
                return redirect(url_for('super_admin_dashboard'))
        else:
            # Regular student
            user_response = supabase.table('users').select('school_id, grade').eq('username', session['user_id']).execute()
            if not user_response.data:
                flash('User data not found.', 'danger')
                return redirect(url_for('student_dashboard'))
            user_data = user_response.data[0]
        
        # Get materials for student's grade and school
        materials_response = supabase.table('study_materials')\
            .select('*')\
            .eq('school_id', user_data['school_id'])\
            .eq('grade_level', user_data['grade'])\
            .order('created_at', desc=True)\
            .execute()
        
        materials = materials_response.data if materials_response.data else []
        
        return render_template('student_materials.html', materials=materials)
        
    except Exception as e:
        logger.error(f"Student materials error: {e}")
        flash('Error loading study materials.', 'danger')
        return redirect(url_for('student_dashboard'))

@app.route('/material/delete/<material_id>', methods=['POST'])
@teacher_required
def delete_material(material_id):
    """Delete a study material"""
    supabase = get_supabase()
    
    # Verify ownership
    material_response = supabase.table('study_materials').select('created_by').eq('id', material_id).execute()
    if material_response.data and material_response.data[0]['created_by'] == session['user_id']:
        supabase.table('study_materials').delete().eq('id', material_id).execute()
        flash('Material deleted successfully!', 'success')
    else:
        flash('Access denied or material not found.', 'danger')
    
    return redirect(url_for('teacher_materials'))

# ===== AI ROUTES WITH RATE LIMITING =====
@app.route('/ai/explain/<material_id>')
@login_required
def ai_explain(material_id):
    """AI explanation with production rate limiting"""
    # Rate limiting check
    if not check_ai_rate_limit(session['user_id'], 'ai_explain'):
        flash('🚫 AI usage limit reached (20 requests per hour). Please try again later.', 'warning')
        return redirect(request.referrer or url_for('student_materials'))
    
    try:
        supabase = get_supabase()
        
        # Get material details
        material_response = supabase.table('study_materials').select('*').eq('id', material_id).execute()
        material = material_response.data[0] if material_response.data else None
        
        if not material:
            flash('Material not found.', 'danger')
            return redirect(request.referrer or url_for('student_materials'))
        
        # Prepare content for AI
        content = ""
        material_type = material['material_type']
        
        if material_type == 'text':
            content = material['content_text'] or ""
        elif material_type == 'web' and material['web_url']:
            content = extract_webpage_content(material['web_url']) or "Web content unavailable"
        else:
            content = material['description'] or material['title']
        
        # Generate AI explanation
        explanation = generate_ai_explanation(content, material_type, material['title'])
        
        return render_template('ai_explanation.html', 
                             material=material, 
                             explanation=explanation,
                             type='explanation')
                             
    except Exception as e:
        logger.error(f"AI explanation error: {e}")
        # Fallback to study guide
        supabase = get_supabase()
        material_response = supabase.table('study_materials').select('*').eq('id', material_id).execute()
        material = material_response.data[0] if material_response.data else None
        
        fallback_explanation = get_fallback_explanation(
            material['title'] if material else "Study Material",
            material['material_type'] if material else 'text'
        )
        
        return render_template('ai_explanation.html', 
                             material=material or {'title': 'Study Material'}, 
                             explanation=fallback_explanation,
                             type='explanation')

@app.route('/ai/summarize/<material_id>')
@login_required
def ai_summarize(material_id):
    """AI summary with production rate limiting"""
    # Rate limiting check
    if not check_ai_rate_limit(session['user_id'], 'ai_summarize'):
        flash('🚫 AI usage limit reached (20 requests per hour). Please try again later.', 'warning')
        return redirect(request.referrer or url_for('student_materials'))
    
    try:
        supabase = get_supabase()
        
        # Get material details
        material_response = supabase.table('study_materials').select('*').eq('id', material_id).execute()
        material = material_response.data[0] if material_response.data else None
        
        if not material:
            flash('Material not found.', 'danger')
            return redirect(request.referrer or url_for('student_materials'))
        
        # Prepare content for AI
        content = ""
        material_type = material['material_type']
        
        if material_type == 'text':
            content = material['content_text'] or ""
        elif material_type == 'web' and material['web_url']:
            content = extract_webpage_content(material['web_url']) or "Web content unavailable"
        else:
            content = material['description'] or material['title']
        
        # Generate AI summary
        summary = generate_ai_summary(content, material_type, material['title'])
        
        return render_template('ai_explanation.html', 
                             material=material, 
                             explanation=summary,
                             type='summary')
                             
    except Exception as e:
        logger.error(f"AI summary error: {e}")
        # Fallback to summary framework
        supabase = get_supabase()
        material_response = supabase.table('study_materials').select('*').eq('id', material_id).execute()
        material = material_response.data[0] if material_response.data else None
        
        fallback_summary = get_fallback_summary(
            material['title'] if material else "Study Material", 
            material['material_type'] if material else 'text'
        )
        
        return render_template('ai_explanation.html', 
                             material=material or {'title': 'Study Material'}, 
                             explanation=fallback_summary,
                             type='summary')

@app.route('/student/uploaded/<path:filename>')
def uploaded_files(filename):
    """Handle requests for uploaded files"""
    flash('📁 File storage is currently being set up. Your teachers are working on making files available for download soon!', 'info')
    return redirect(url_for('student_materials'))

@app.route('/uploads/<filename>')
def serve_uploaded_file(filename):
    """Serve uploaded study material files"""
    try:
        return send_from_directory(UPLOAD_FOLDER, filename)
    except Exception as e:
        logger.error(f"File serving error: {e}")
        flash('File not found.', 'danger')
        return redirect(url_for('student_materials'))
    
@app.route('/download/<filename>')
@login_required
def download_file(filename):
    """Download study material files"""
    try:
        # Security check: ensure the file exists and user has access
        safe_filename = secure_filename(filename)
        file_path = os.path.join(UPLOAD_FOLDER, safe_filename)
        
        if not os.path.exists(file_path):
            flash('File not found.', 'danger')
            return redirect(url_for('student_materials'))
        
        # Send file for download with original filename
        return send_from_directory(
            UPLOAD_FOLDER, 
            safe_filename, 
            as_attachment=True,
            download_name=filename  # Use original filename for download
        )
        
    except Exception as e:
        logger.error(f"File download error: {e}")
        flash('Error downloading file.', 'danger')
        return redirect(url_for('student_materials'))

@app.route('/debug/ai-status')
@login_required
def debug_ai_status():
    """Check AI configuration status"""
    status = {
        'api_key_configured': bool(GOOGLE_API_KEY),
        'api_key_length': len(GOOGLE_API_KEY) if GOOGLE_API_KEY else 0,
        'available_models': test_gemini_models(),
        'test_result': 'Not tested'
    }
    
    # Test with a WORKING model from your list
    if GOOGLE_API_KEY:
        try:
            model = genai.GenerativeModel("models/gemini-2.0-flash")
            response = model.generate_content("Say 'AI is working' in one word.")
            status['test_result'] = response.text if response.text else "No response"
            status['test_success'] = True
        except Exception as e:
            status['test_result'] = f"Error: {str(e)}"
            status['test_success'] = False
    
    return jsonify(status)

@app.route('/debug/teacher-context')
@super_admin_required
def debug_teacher_context():
    """Debug teacher context switching"""
    current_teacher = session.get('current_teacher_id')
    current_school = session.get('current_school_id')
    
    supabase = get_supabase()
    
    debug_info = {
        'current_teacher': current_teacher,
        'current_school': current_school,
        'session_user': session.get('user_id')
    }
    
    if current_teacher:
        teacher_data = get_user_by_username(current_teacher)
        debug_info['teacher_data'] = teacher_data
        
        if teacher_data and teacher_data.get('school_id'):
            # Check students in that school
            students = supabase.table("users").select("*").eq("school_id", teacher_data['school_id']).eq("role", "student").execute()
            debug_info['students_in_school'] = students.data if students.data else []
            
            # Check prompts in that school
            prompts = supabase.table("prompts").select("*").eq("school_id", teacher_data['school_id']).execute()
            debug_info['prompts_in_school'] = prompts.data if prompts.data else []
    
    return jsonify(debug_info)

# ===== IGCSE SCIENCE MCQ REVISION FEATURE =====
@app.route('/science/revision')
@login_required
def science_revision():
    """IGCSE Science Revision Dashboard"""
    return render_template('science_revision.html')

@app.route('/science/quiz/start')
@login_required
def start_science_quiz():
    """Start a new science quiz with 20 random questions"""
    supabase = get_supabase()
    
    try:
        # Get ALL questions first, then shuffle and pick 20
        response = supabase.table('igcse_science_questions').select('*').execute()
        all_questions = response.data if response.data else []
        
        if not all_questions:
            flash('No science questions available in the database yet.', 'warning')
            return redirect(url_for('science_revision'))
        
        # Shuffle and pick 20 random questions
        import random
        random.shuffle(all_questions)
        questions = all_questions[:20]
        
        return render_template('science_quiz.html', questions=questions)
        
    except Exception as e:
        logger.error(f"Science quiz error: {e}")
        flash('Error starting science quiz. Please try again.', 'danger')
        return redirect(url_for('science_revision'))

@app.route('/science/quiz/submit', methods=['POST'])
@login_required
def submit_science_quiz():
    """Submit and grade science quiz - UPDATED FOR YOUR DATABASE SCHEMA"""
    supabase = get_supabase()
    
    try:
        # Check if any answers were submitted
        if not request.form:
            flash('No answers submitted. Please complete the quiz.', 'warning')
            return redirect(url_for('start_science_quiz'))
        
        score = 0
        total_questions = 0
        question_responses = []
        question_ids = []
        
        # Get all correct answers for the questions in this quiz
        form_question_ids = [key for key in request.form.keys() if key != 'csrf_token']
        
        if form_question_ids:
            response = supabase.table('igcse_science_questions')\
                .select('id, question_text, option_a, option_b, option_c, option_d, correct_answer, explanation, topic, difficulty')\
                .in_('id', form_question_ids)\
                .execute()
            
            correct_answers = {q['id']: q['correct_answer'] for q in response.data} if response.data else {}
            question_details = {q['id']: q for q in response.data} if response.data else {}
            
            # Grade each question
            for question_id, student_answer in request.form.items():
                if question_id == 'csrf_token':  # Skip CSRF token
                    continue
                    
                if not student_answer:  # Skip empty answers
                    continue
                    
                total_questions += 1
                question_ids.append(question_id)
                is_correct = correct_answers.get(question_id) == student_answer
                
                if is_correct:
                    score += 1
                
                question_responses.append({
                    'question_id': question_id,
                    'student_answer': student_answer,
                    'correct_answer': correct_answers.get(question_id),
                    'is_correct': is_correct,
                    'question_text': question_details.get(question_id, {}).get('question_text', ''),
                    'explanation': question_details.get(question_id, {}).get('explanation', ''),
                    'topic': question_details.get(question_id, {}).get('topic', ''),
                    'options': {
                        'A': question_details.get(question_id, {}).get('option_a', ''),
                        'B': question_details.get(question_id, {}).get('option_b', ''),
                        'C': question_details.get(question_id, {}).get('option_c', ''),
                        'D': question_details.get(question_id, {}).get('option_d', '')
                    }
                })
        
        # Calculate percentage
        percentage = round((score / total_questions) * 100) if total_questions > 0 else 0
        
        # Save attempt to database - MATCHING YOUR SCHEMA
        attempt_data = {
            'student_id': session['user_id'],
            'questions_attempted': question_ids,  # Array of question IDs
            'score': score,
            'total_questions': total_questions,
            'completed_at': datetime.now().isoformat()
        }
        
        result = supabase.table('student_quiz_attempts').insert(attempt_data).execute()
        
        return render_template('science_quiz_results.html',
                             score=score,
                             total_questions=total_questions,
                             percentage=percentage,
                             question_responses=question_responses)
        
    except Exception as e:
        logger.error(f"Science quiz submission error: {e}")
        flash('Error submitting quiz. Please try again.', 'danger')
        return redirect(url_for('science_revision'))

@app.route('/science/quiz/history')
@login_required
def science_quiz_history():
    """View previous quiz attempts - UPDATED FOR YOUR SCHEMA"""
    supabase = get_supabase()
    
    try:
        response = supabase.table('student_quiz_attempts')\
            .select('*')\
            .eq('student_id', session['user_id'])\
            .order('completed_at', desc=True)\
            .limit(10)\
            .execute()
        
        attempts = response.data if response.data else []
        
        # Calculate percentage for each attempt (since it's not stored in your schema)
        for attempt in attempts:
            if attempt['total_questions'] > 0:
                attempt['percentage'] = round((attempt['score'] / attempt['total_questions']) * 100)
            else:
                attempt['percentage'] = 0
        
        return render_template('science_quiz_history.html', attempts=attempts)
        
    except Exception as e:
        logger.error(f"Science quiz history error: {e}")
        flash('Error loading quiz history.', 'danger')
        return redirect(url_for('science_revision'))


# Production configuration
if __name__ == '__main__':
    # Use environment variable to determine debug mode
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    
    if debug_mode:
        print("🚀 Running in DEVELOPMENT mode with debug enabled")
        app.run(debug=True, host='0.0.0.0', port=5000)
    else:
        print("🚀 Running in PRODUCTION mode")
        app.run(debug=False, host='0.0.0.0', port=5000)