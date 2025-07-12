import os
import re
import argparse
import glob
import shutil
from datetime import datetime
from collections import defaultdict

def setup_logging(filename):
    # Настраиваем файлы логов с временной меткой и именем входного файла
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    base_filename = os.path.splitext(os.path.basename(filename))[0]
    log_file = f"copy_log_{timestamp}_{base_filename}.txt"
    error_log_file = f"error_log_{timestamp}_{base_filename}.txt"
    not_found_log_file = f"not_found_log_{timestamp}_{base_filename}.txt"
    return log_file, error_log_file, not_found_log_file

def log_message(log_file, message, error_log_file=None, not_found_log_file=None, is_error=False, is_not_found=False, console_output=True):
    # Записываем сообщение в соответствующий лог и, при необходимости, в консоль
    if is_not_found and not_found_log_file:
        with open(not_found_log_file, 'a', encoding='utf-8') as f:
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: {message}\n")
    else:
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: {message}\n")
        if is_error and error_log_file:
            with open(error_log_file, 'a', encoding='utf-8') as f:
                f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: {message}\n")
    if console_output:
        print(message)

def extract_base_content_directory(input_file):
    # Извлекаем base_content_directory из плейлиста
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            for line in f:
                if '"base_content_directory"' in line:
                    match = re.search(r'"base_content_directory":\s*"(.*?)"', line.strip())
                    if match:
                        return match.group(1)
    except Exception as e:
        return None
    return None

def extract_file_info(line, base_content_directory):
    # Проверяем тип строки: с # или без #
    if base_content_directory:
        # Экранируем base_content_directory для использования в регулярном выражении
        escaped_base = re.escape(base_content_directory)
        if '#' in line:
            # Строка с #: извлекаем имя файла, псевдоним и имя системы
            pattern = rf'"path":\s*"{escaped_base}/([^/]+)/([^/]+?)\.[^/]+#(.+?)\.[^.]+"'
            match = re.search(pattern, line)
            if match:
                system_name = match.group(1)  # Имя системы (nes)
                file_name = match.group(2)    # Имя файла (до последней точки перед #)
                alias = match.group(3)        # Псевдоним (до последней точки)
                return file_name, alias, system_name
        else:
            # Строка без #: извлекаем имя файла, псевдоним = имя файла, имя системы
            pattern = rf'"path":\s*"{escaped_base}/([^/]+)/([^/]+?)\.[^/]+"'
            match = re.search(pattern, line)
            if match:
                system_name = match.group(1)  # Имя системы (nes)
                file_name = match.group(2)    # Имя файла (до последней точки)
                alias = file_name             # Псевдоним совпадает с именем файла
                return file_name, alias, system_name
    # Если base_content_directory не указан или строка не соответствует, используем старый метод
    if '#' in line:
        pattern = r'"path": ".*/([^/]+?)\.[^/]+#(.+?)\.[^.]+"'
        match = re.search(pattern, line)
        if match:
            file_name = match.group(1)
            alias = match.group(2)
            return file_name, alias, None
    else:
        pattern = r'"path": ".*/([^/]+?)\.[^/]+"'
        match = re.search(pattern, line)
        if match:
            file_name = match.group(1)
            alias = file_name
            return file_name, alias, None
    return None, None, None

def get_category_and_priority(directory):
    # Определяем категорию и приоритет на основе имени каталога
    dir_name = os.path.basename(directory).lower()
    categories = {
        'art': ('Named_Snaps', 0),
        'boxart': ('Named_Boxarts', 1),
        'cartridge': ('Named_Titles', 2),
        'screenshot': ('Named_Titles', 3)
    }
    return categories.get(dir_name, (None, -1))

def copy_png_files(input_file, search_dir, log_file, error_log_file, not_found_log_file):
    # Инициализируем счетчики для статистики
    stats = {
        'lines_processed': 0,
        'files_found': 0,
        'files_copied': 0,
        'errors': 0
    }
    
    # Проверяем, существует ли входной файл
    if not os.path.isfile(input_file):
        log_message(log_file, f"Ошибка: Файл {input_file} не существует", error_log_file, is_error=True, console_output=True)
        stats['errors'] += 1
        return stats
    
    # Проверяем, существует ли директория
    if not os.path.isdir(search_dir):
        log_message(log_file, f"Ошибка: Каталог {search_dir} не существует", error_log_file, is_error=True, console_output=True)
        stats['errors'] += 1
        return stats
    
    log_message(log_file, f"Начало обработки файла: {input_file}", console_output=True)
    log_message(log_file, f"Каталог поиска: {search_dir}", console_output=True)
    
    # Получаем имя LPL файла без расширения
    lpl_name = os.path.splitext(os.path.basename(input_file))[0]
    
    # Извлекаем base_content_directory
    base_content_directory = extract_base_content_directory(input_file)
    if base_content_directory:
        log_message(log_file, f"Базовый путь: {base_content_directory}", console_output=True)
    
    # Извлекаем system_name из первой подходящей строки
    system_name = None
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            for line in lines:
                if '"path"' in line:
                    _, _, system_name = extract_file_info(line.strip(), base_content_directory)
                    if system_name:
                        break
    except Exception as e:
        log_message(log_file, f"Ошибка при чтении файла {input_file}: {e}", error_log_file, is_error=True, console_output=True)
        stats['errors'] += 1
        return stats
    
    # Определяем каталог для поиска
    search_path = search_dir
    if system_name:
        search_path = os.path.join(search_dir, system_name)
        log_message(log_file, f"Каталог поиска для системы {system_name}: {search_path}", console_output=True)
        if not os.path.isdir(search_path):
            log_message(log_file, f"Ошибка: Каталог {search_path} не существует", error_log_file, is_error=True, console_output=True)
            stats['errors'] += 1
            return stats
    else:
        log_message(log_file, f"Каталог поиска (система не определена): {search_path}", console_output=True)
    
    # Читаем файл построчно для обработки
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        log_message(log_file, f"Ошибка при чтении файла {input_file}: {e}", error_log_file, is_error=True, console_output=True)
        stats['errors'] += 1
        return stats
    
    # Обрабатываем каждую строку
    for line in lines:
        stats['lines_processed'] += 1
        file_name, alias, _ = extract_file_info(line.strip(), base_content_directory)
        if file_name and alias:
            # Собираем все подходящие файлы и группируем по категориям
            files_by_category = defaultdict(list)
            for root, _, files in os.walk(search_path):
                category, priority = get_category_and_priority(root)
                if category is None:  # Пропускаем каталоги, не входящие в список
                    continue
                for file in files:
                    if file.startswith(file_name) and file.endswith('.png'):
                        stats['files_found'] += 1
                        files_by_category[category].append((os.path.join(root, file), priority))
            
            # Если файлы найдены, копируем их по категориям
            found = bool(files_by_category)
            copied = False
            copy_result = "не скопирован"
            
            if found:
                for category, files in files_by_category.items():
                    # Сортируем файлы по приоритету (высший приоритет — последний)
                    files.sort(key=lambda x: x[1])
                    for old_path, _ in files:
                        # Формируем целевой путь
                        new_dir = os.path.join(search_dir, 'retroarch', 'thumbnails', lpl_name, category)
                        new_file = f"{alias}.png"
                        new_path = os.path.join(new_dir, new_file)
                        
                        try:
                            # Создаем целевую директорию, если она не существует
                            os.makedirs(new_dir, exist_ok=True)
                            # Копируем файл (перезаписываем, если уже существует)
                            shutil.copy2(old_path, new_path)
                            stats['files_copied'] += 1
                            copied = True
                        except OSError as e:
                            stats['errors'] += 1
                            log_message(log_file, f"{line.strip()}, {file_name}, {alias}, найден, не скопирован, Ошибка: {e}", error_log_file, is_error=True, console_output=True)
                
                copy_result = "скопирован" if copied else copy_result
                log_message(log_file, f"{line.strip()}, {file_name}, {alias}, найден, {copy_result}", console_output=False)
            else:
                log_message(log_file, f"{line.strip()}, {file_name}, {alias}, не найден, не скопирован", not_found_log_file=not_found_log_file, is_not_found=True, console_output=True)
    
    return stats

def print_statistics(stats, log_file, error_log_file):
    # Формируем и выводим статистику
    stats_message = (
        "\n=== Статистика выполнения ===\n"
        f"Обработано строк: {stats['lines_processed']}\n"
        f"Найдено PNG файлов: {stats['files_found']}\n"
        f"Успешно скопировано файлов: {stats['files_copied']}\n"
        f"Ошибок: {stats['errors']}\n"
        "==========================="
    )
    log_message(log_file, stats_message, console_output=True)

def main():
    # Настраиваем парсер аргументов командной строки
    parser = argparse.ArgumentParser(description="Копирование PNG файлов на основе данных из файла")
    parser.add_argument("--input_file", help="Путь к файлу со строками путей")
    parser.add_argument("--search_dir", help="Путь к каталогу для поиска PNG файлов")
    
    # Получаем аргументы
    args = parser.parse_args()
    
    current_dir = os.getcwd()  # Текущий каталог
    
    if args.input_file and args.search_dir:
        # Режим с параметрами командной строки
        log_file, error_log_file, not_found_log_file = setup_logging(args.input_file)
        stats = copy_png_files(args.input_file, args.search_dir, log_file, error_log_file, not_found_log_file)
        print_statistics(stats, log_file, error_log_file)
    else:
        # Режим без параметров: поиск *.lpl файлов в текущем каталоге
        lpl_files = glob.glob(os.path.join(current_dir, "*.lpl"))
        if not lpl_files:
            print("В текущем каталоге не найдено *.lpl файлов")
            return
        
        for lpl_file in lpl_files:
            log_file, error_log_file, not_found_log_file = setup_logging(lpl_file)
            log_message(log_file, f"Обработка файла: {lpl_file}", console_output=True)
            stats = copy_png_files(lpl_file, current_dir, log_file, error_log_file, not_found_log_file)
            print_statistics(stats, log_file, error_log_file)

if __name__ == "__main__":
    main()