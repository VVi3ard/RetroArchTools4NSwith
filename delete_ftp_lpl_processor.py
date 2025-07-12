import json
import os
import logging
from ftplib import FTP
from io import BytesIO
import time
import sys
from datetime import datetime

# ANSI-цвета
class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'

# Проверка поддержки цветов в Windows (без colorama)
if sys.platform == 'win32':
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except:
        class Colors:
            RED = GREEN = YELLOW = BLUE = RESET = ''

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('general.log', encoding='utf-8'),
    ]
)

class ColorConsoleHandler(logging.StreamHandler):
    def emit(self, record):
        try:
            msg = self.format(record)
            if "DRY-RUN MODE" in msg:
                msg = f"{Colors.YELLOW}{msg}{Colors.RESET}"
            elif "[OK]" in msg:
                msg = msg.replace("[OK]", f"{Colors.GREEN}[OK]{Colors.RESET}")
            elif "[ERROR]" in msg:
                msg = msg.replace("[ERROR]", f"{Colors.RED}[ERROR]{Colors.RESET}")
            sys.stdout.write(msg + '\n')
            sys.stdout.flush()
        except Exception:
            self.handleError(record)

console_logger = logging.getLogger('console')
console_handler = ColorConsoleHandler()
console_handler.setFormatter(logging.Formatter('%(message)s'))
console_logger.addHandler(console_handler)

error_logger = logging.getLogger('error_logger')
error_handler = logging.FileHandler('error.log', encoding='utf-8')
error_handler.setLevel(logging.ERROR)
error_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
error_logger.addHandler(error_handler)

processed_logger = logging.getLogger('processed_logger')
processed_handler = logging.FileHandler('processed.log', encoding='utf-8')
processed_handler.setLevel(logging.INFO)
processed_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
processed_logger.addHandler(processed_handler)

def get_config():
    return {
        "ftp_host": "192.168.1.56",
        "ftp_port": 5000,
        "ftp_user": "anonymous",
        "ftp_pass": "anonymous",
        "dry_run": True
    }

def ftp_connect():
    config = get_config()
    ftp = FTP()
    ftp.connect(config["ftp_host"], config["ftp_port"])
    ftp.login(config["ftp_user"], config["ftp_pass"])
    console_logger.info(f"Подключено к FTP: {config['ftp_host']}:{config['ftp_port']} (пользователь: {config['ftp_user']})")
    return ftp

def ftp_get_size(ftp, path):
    try:
        size = ftp.size(path)
        return size if size is not None else 0
    except Exception as e:
        error_logger.error(f"Ошибка при получении размера {path}: {e}")
        return 0

def ftp_download_json(ftp, path):
    buffer = BytesIO()
    ftp.retrbinary(f'RETR {path}', buffer.write)
    buffer.seek(0)
    return json.load(buffer)

def ftp_backup(ftp, path):
    buffer = BytesIO()
    ftp.retrbinary(f'RETR {path}', buffer.write)
    buffer.seek(0)
    ftp.storbinary(f'STOR {path}.bkp', buffer)

def ftp_move_file(ftp, src, dest):
    config = get_config()
    size = ftp_get_size(ftp, src)
    if config['dry_run']:
        logging.info(f"[DRY-RUN] Перемещение: {src} -> {dest}")
        return size
    temp = BytesIO()
    ftp.retrbinary(f'RETR {src}', temp.write)
    temp.seek(0)
    ftp_delete_safe(ftp, src)
    ftp_mkdirs(ftp, os.path.dirname(dest))
    ftp.storbinary(f'STOR {dest}', temp)
    return size

def ftp_delete_safe(ftp, path):
    try:
        ftp.delete(path)
    except Exception:
        pass

def ftp_mkdirs(ftp, path):
    parts = path.strip('/').split('/')
    current = ''
    for part in parts:
        current += f'/{part}'
        try:
            ftp.mkd(current)
        except Exception:
            pass

def ftp_walk(ftp, dir_path):
    file_paths = []
    stack = [dir_path]
    while stack:
        current = stack.pop()
        try:
            lines = []
            ftp.retrlines(f'LIST {current}', lines.append)
            for line in lines:
                parts = line.split()
                if not parts:
                    continue
                if len(parts) < 8:
                    continue
                name = ' '.join(parts[8:])
                full_path = f"{current}/{name}" if current != '/' else f"/{name}"
                if line.startswith('d'):
                    stack.append(full_path)
                else:
                    file_paths.append(full_path)
        except Exception as e:
            error_logger.error(f"Ошибка при обходе {current}: {e}")
            continue
    return file_paths

def main():
    start_time = time.time()
    try:
        config = get_config()
        if config['dry_run']:
            console_logger.info(f"\n{Colors.YELLOW}=== DRY-RUN MODE: Файлы не будут перемещены ==={Colors.RESET}\n")

        ftp = ftp_connect()
        dry_run = config['dry_run']

        lpl_path = '/retroarch/playlists/delete.lpl'
        backup_path = f"{lpl_path}.bkp"

        console_logger.info("Создание бэкапа...")
        ftp_backup(ftp, lpl_path)
        data = ftp_download_json(ftp, lpl_path)

        base_content_directory = data.get('base_content_directory', '')
        items = data.get('items', [])

        console_logger.info(f"Каталог ROM: {base_content_directory}")
        console_logger.info(f"Найдено записей: {len(items)}")

        moved_roms = 0
        moved_thumbs = 0
        total_roms_size = 0
        total_thumbs_size = 0
        error_count = 0
        processed_items = []

        for item in items:
            rom_size = 0
            thumbs_size = 0
            thumb_count = 0
            try:
                path = item.get('path', '')
                if '#' not in path:
                    raise ValueError(f"Некорректный путь: {path}")

                file_path, alias_ext = path.split('#')
                alias = alias_ext.rsplit('.', 1)[0]
                db_name = item.get('db_name', '').rsplit('.', 1)[0]

                src_rom = file_path
                dest_rom = f"/del{src_rom}"

                rom_size = ftp_move_file(ftp, src_rom, dest_rom)
                moved_roms += 1
                total_roms_size += rom_size

                thumbs_base = f"/retroarch/thumbnails/{db_name}"
                all_files = ftp_walk(ftp, thumbs_base)
                thumb_matches = [f for f in all_files if f.endswith(f"/{alias}.png")]

                for thumb in thumb_matches:
                    rel_path = thumb[len(thumbs_base):]
                    dest_thumb = f"/del/retroarch/thumbnails/{db_name}{rel_path}"
                    thumb_size = ftp_move_file(ftp, thumb, dest_thumb)
                    thumbs_size += thumb_size
                    thumb_count += 1

                moved_thumbs += thumb_count
                total_thumbs_size += thumbs_size

                console_logger.info(f"[OK] {os.path.basename(src_rom)}, миниатюр: {thumb_count}")
                processed_logger.info(json.dumps(item, ensure_ascii=False))
                processed_items.append(item)

            except Exception as e:
                error_count += 1
                console_logger.info(f"[ERROR] {os.path.basename(path)}, {str(e)}")
                error_logger.error(f"Ошибка в {path}: {e}")

        for item in processed_items:
            items.remove(item)

        if not dry_run:
            buffer = BytesIO()
            buffer.write(json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8'))
            buffer.seek(0)
            ftp.storbinary(f'STOR {lpl_path}', buffer)

        total_size_mb = (total_roms_size + total_thumbs_size) / (1024 * 1024)
        elapsed_time = time.time() - start_time

        console_logger.info(f"\n{Colors.BLUE}=== Итоги ===")
        console_logger.info(f"ROM-файлов: {moved_roms} ({total_roms_size / 1024:.2f} KB)")
        console_logger.info(f"Миниатюр: {moved_thumbs} ({total_thumbs_size / 1024:.2f} KB)")
        console_logger.info(f"Общий размер: {total_size_mb:.2f} MB")
        console_logger.info(f"Время работы: {elapsed_time:.2f} сек")
        console_logger.info(f"Ошибок: {error_count}{Colors.RESET}")

        ftp.quit()

    except Exception as e:
        error_logger.error(f"Критическая ошибка: {e}")
        console_logger.info(f"{Colors.RED}[ERROR] {str(e)}{Colors.RESET}")

if __name__ == "__main__":
    main()