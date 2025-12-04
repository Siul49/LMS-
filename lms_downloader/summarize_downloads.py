import os

def summarize_downloads(root_dir="downloads"):
    if not os.path.exists(root_dir):
        print(f"Directory '{root_dir}' does not exist.")
        return

    print(f"Scanning '{root_dir}' for downloaded files...\n")
    
    total_files = 0
    courses = sorted(os.listdir(root_dir))
    
    for course in courses:
        course_path = os.path.join(root_dir, course)
        if not os.path.isdir(course_path):
            continue
            
        print(f"[{course}]")
        weeks = sorted(os.listdir(course_path))
        course_files = 0
        
        for week in weeks:
            week_path = os.path.join(course_path, week)
            if not os.path.isdir(week_path):
                continue
                
            files = os.listdir(week_path)
            if files:
                print(f"  - {week}: {len(files)} files")
                for f in files:
                    print(f"    * {f}")
                course_files += len(files)
            else:
                print(f"  - {week}: (No files)")
        
        print(f"  => Total for course: {course_files} files\n")
        total_files += course_files

    print(f"Total files downloaded across all courses: {total_files}")

if __name__ == "__main__":
    summarize_downloads()
