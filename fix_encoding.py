import sys

def fix_mojibake(input_path, output_path):
    print(f"Reading {input_path}...")
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        print("Attempting to fix encoding (utf8 -> latin1 bytes -> utf8 text)...")
        # The key logic: Re-interpret the "UTF-8 encoded Latin-1 characters" back to their original bytes,
        # then decode those bytes as UTF-8.
        fixed_content = content.encode('cp1252').decode('utf-8')
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(fixed_content)
            
        print(f"Success! Fixed file written to {output_path}")
        
    except UnicodeEncodeError as e:
        print(f"Encode Error (cp1252): {e}")
        # Try latin1 if cp1252 fails (cp1252 is superset of latin1 but sometimes handling differs)
        try:
            fixed_content = content.encode('latin1').decode('utf-8')
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(fixed_content)
            print(f"Success (latin1)! Fixed file written to {output_path}")
        except Exception as e2:
            print(f"Retry failed: {e2}")
            sys.exit(1)
            
    except UnicodeDecodeError as e:
        print(f"Decode Error (utf8): {e}")
        sys.exit(1)

if __name__ == "__main__":
    fix_mojibake('/home/chaisen/projects/cv/db/full_backup.sql', '/home/chaisen/projects/cv/db/fixed_dump.sql')
