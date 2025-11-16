"""
Database Diagnostic Script
Run this to check and fix your database structure
"""

from supabase import create_client
import os
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

def get_supabase():
    """Initialize Supabase client"""
    url = os.getenv('SUPABASE_URL')
    key = os.getenv('SUPABASE_KEY')
    
    if not url or not key:
        print("❌ ERROR: Missing SUPABASE_URL or SUPABASE_KEY environment variables")
        print("\n💡 Make sure you have a .env file with:")
        print("   SUPABASE_URL=your_url_here")
        print("   SUPABASE_KEY=your_key_here")
        print("\nOr set them in your environment:")
        print("   Windows: set SUPABASE_URL=your_url")
        print("   Linux/Mac: export SUPABASE_URL=your_url")
        return None
    
    return create_client(url, key)

def run_diagnostic():
    """Run complete database diagnostic"""
    print("\n" + "="*60)
    print("🔍 STARTING DATABASE DIAGNOSTIC")
    print("="*60 + "\n")
    
    supabase = get_supabase()
    if not supabase:
        return
    
    # Check 1: Verify prompts table structure
    print("📋 CHECK 1: Verifying 'prompts' table columns...")
    try:
        # Fetch one prompt to see structure
        test_query = supabase.table('prompts').select('*').limit(1).execute()
        
        if test_query.data:
            columns = list(test_query.data[0].keys())
            print(f"✅ Found {len(columns)} columns in 'prompts' table")
            print(f"   Columns: {', '.join(columns)}")
            
            # Check for critical columns
            required_cols = ['id', 'title', 'description', 'grade_level', 'subject', 
                           'assessment_type', 'total_points', 'instructions', 'due_date']
            missing_cols = [col for col in required_cols if col not in columns]
            
            if missing_cols:
                print(f"\n⚠️  WARNING: Missing columns: {', '.join(missing_cols)}")
                print("\n   To fix, run this SQL in Supabase SQL Editor:")
                for col in missing_cols:
                    if col == 'subject':
                        print(f"   ALTER TABLE prompts ADD COLUMN {col} text DEFAULT 'general';")
                    elif col == 'assessment_type':
                        print(f"   ALTER TABLE prompts ADD COLUMN {col} text DEFAULT 'written';")
                    elif col == 'total_points':
                        print(f"   ALTER TABLE prompts ADD COLUMN {col} integer DEFAULT 10;")
                    elif col == 'instructions':
                        print(f"   ALTER TABLE prompts ADD COLUMN {col} text;")
                    elif col == 'due_date':
                        print(f"   ALTER TABLE prompts ADD COLUMN {col} timestamp;")
            else:
                print("✅ All required columns present!")
        else:
            print("⚠️  No prompts found in database")
    except Exception as e:
        print(f"❌ ERROR checking table structure: {e}")
    
    # Check 2: Find prompts with missing subjects
    print("\n📋 CHECK 2: Finding prompts with missing subjects...")
    try:
        all_prompts = supabase.table('prompts').select('id, title, subject').execute()
        
        if all_prompts.data:
            print(f"✅ Found {len(all_prompts.data)} total prompts")
            
            missing_subject = [p for p in all_prompts.data if not p.get('subject') or p.get('subject') == '']
            
            if missing_subject:
                print(f"\n⚠️  WARNING: {len(missing_subject)} prompts missing subject field:")
                for prompt in missing_subject[:5]:  # Show first 5
                    print(f"   - ID: {prompt['id']} | Title: {prompt['title']}")
                if len(missing_subject) > 5:
                    print(f"   ... and {len(missing_subject) - 5} more")
                
                print("\n   To fix, run this SQL in Supabase:")
                print("   UPDATE prompts SET subject = 'general' WHERE subject IS NULL OR subject = '';")
            else:
                print("✅ All prompts have subjects assigned!")
        else:
            print("⚠️  No prompts in database yet")
    except Exception as e:
        print(f"❌ ERROR checking subjects: {e}")
    
    # Check 3: Verify submissions table has grade column
    print("\n📋 CHECK 3: Verifying 'submissions' table has grade column...")
    try:
        test_sub = supabase.table('submissions').select('*').limit(1).execute()
        
        if test_sub.data:
            if 'grade' in test_sub.data[0]:
                print("✅ 'grade' column exists in submissions table")
            else:
                print("⚠️  WARNING: 'grade' column missing from submissions")
                print("   To fix, run this SQL:")
                print("   ALTER TABLE submissions ADD COLUMN grade integer;")
        else:
            print("⚠️  No submissions in database yet")
    except Exception as e:
        print(f"❌ ERROR checking submissions: {e}")
    
    # Check 4: Subject distribution
    print("\n📋 CHECK 4: Analyzing subject distribution...")
    try:
        all_prompts = supabase.table('prompts').select('subject').execute()
        
        if all_prompts.data:
            subjects = {}
            for p in all_prompts.data:
                subj = p.get('subject', 'unknown')
                subjects[subj] = subjects.get(subj, 0) + 1
            
            print("✅ Subject distribution:")
            for subj, count in sorted(subjects.items(), key=lambda x: x[1], reverse=True):
                print(f"   - {subj.title()}: {count} prompts")
    except Exception as e:
        print(f"❌ ERROR analyzing subjects: {e}")
    
    # Summary
    print("\n" + "="*60)
    print("✅ DIAGNOSTIC COMPLETE")
    print("="*60)
    print("\nNext steps:")
    print("1. Fix any missing columns using the SQL commands above")
    print("2. Update prompts with missing subjects")
    print("3. Use the fixed create_prompt route (provided separately)")
    print("4. Restart your application")
    print("\n")

if __name__ == '__main__':
    run_diagnostic()