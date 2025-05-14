# app.py
import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
from googleapiclient.discovery import build
import openai
import time
import re

# app.py
# ... (імпорти streamlit, pandas, datetime, etc.) ...
import os # Переконайся, що цей імпорт є або додай його

# --- Отримання API ключів ---
# Спочатку намагаємося отримати з секретів Streamlit Cloud (якщо додаток розгорнуто)
# Ці імена змінних YOUTUBE_API_KEY та OPENAI_API_KEY мають збігатися з тими, 
# які ти вкажеш у налаштуваннях секретів на Streamlit Cloud.
YOUTUBE_API_KEY = st.secrets.get("YOUTUBE_API_KEY")
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY")

# Якщо ключі не знайдено в секретах Streamlit Cloud (наприклад, при локальному запуску),
# намагаємося завантажити їх з локального файлу config_keys.py
if not YOUTUBE_API_KEY or not OPENAI_API_KEY:
    # st.sidebar.caption("Ключі не знайдено в Streamlit Secrets, завантажую з config_keys.py") # Для відладки
    try:
        from config_keys import YOUTUBE_API_KEY as YOUTUBE_API_KEY_local
        from config_keys import OPENAI_API_KEY as OPENAI_API_KEY_local
        YOUTUBE_API_KEY = YOUTUBE_API_KEY_local
        OPENAI_API_KEY = OPENAI_API_KEY_local
    except ImportError:
        # Цей st.error буде видно і локально, і в хмарі, якщо ніде немає ключів
        st.error("Помилка: Не вдалося завантажити API ключі. "
                 "Переконайтеся, що вони налаштовані як секрети в Streamlit Cloud (якщо розгорнуто), "
                 "або існує локальний файл config_keys.py з коректними ключами.")
        st.stop() # Зупиняємо виконання, якщо ключі не завантажено

# Фінальна перевірка, чи ключі дійсно є
if not YOUTUBE_API_KEY or not OPENAI_API_KEY:
    st.error("Помилка: YOUTUBE_API_KEY або OPENAI_API_KEY не визначені.")
    st.stop()

# Налаштування OpenAI API ключа (YOUTUBE_API_KEY використовується напряму в функції)
openai.api_key = OPENAI_API_KEY

# ID YouTube-каналу "Армія TV"
CHANNEL_ID = "UCWRZ7gEgbry5FI2-46EX3jA"

# Визначені категорії для аналізу
CATEGORIES = [
    "Танки",  # Про танки, їх бойове застосування
    "Артилерія",  # Про артилерійські системи, РСЗВ, міномети
    "Авіація",  # Про літаки, гелікоптери, повітряні бої, ППО по авіації
    "Бронетехніка",  # Про БМП, БТР, іншу легку/середню бронетехніку (крім танків)
    "Дрони",  # Про розвідувальні та ударні БПЛА, FPV-дрони, РЕБ проти дронів
    "Піхота і гарячі напрямки",  # Про дії піхоти, штурми, бої в містах, репортажі з фронту
    "Героїзм та унікальні історії військових, портретні репортажі", # Інтерв'ю, історії подвигів
    "Навчання",  # Навчальні відео, інструкції, тактична медицина, тренування
    "Огляди зразків озброєння",  # Огляди стрілецької зброї, гранатометів, ПТРК
    "Новини, Стріми, Аналітика", # Зведення новин, стріми з фронту, аналітичні огляди (НОВА)
    "Різне" # Для всього іншого, що не підходить
]
st.set_page_config(layout="wide") # Робимо сторінку ширшою
st.title("🤖 ШІ-Агент для аналізу YouTube-каналу 'Армія TV'")


# --- Тут будуть функції ---

def parse_iso8601_duration(duration_str):
    """
    Парсить тривалість у форматі ISO 8601 (наприклад, "PT1M30S")
    і повертає загальну кількість секунд.
    Відео без тривалості або з форматом "P0D" (часто для прямих трансляцій, що завершилися)
    будуть мати тривалість 0.
    """
    if not duration_str or not duration_str.startswith('PT') or duration_str == 'P0D':
        # P0D іноді зустрічається для відео, які були прямими трансляціями
        return 0

    hours = 0
    minutes = 0
    seconds = 0

    # Видаляємо 'PT' з початку
    duration_str = duration_str[2:]

    # Години
    if 'H' in duration_str:
        parts = duration_str.split('H')
        hours = int(parts[0])
        duration_str = parts[1] if len(parts) > 1 else ''

    # Хвилини
    if 'M' in duration_str:
        parts = duration_str.split('M')
        minutes = int(parts[0])
        duration_str = parts[1] if len(parts) > 1 else ''

    # Секунди
    if 'S' in duration_str:
        parts = duration_str.split('S')
        seconds = int(parts[0])

    total_seconds = hours * 3600 + minutes * 60 + seconds
    return total_seconds

# ... (інші твої функції: @st.cache_data(ttl=3600) def get_channel_videos(...) і т.д.) ...
@st.cache_data(ttl=3600)  # Кешуємо дані на 1 годину, щоб не запитувати YouTube API занадто часто
def get_channel_videos(api_key, channel_id, start_date, end_date):
    """Отримує список відео з каналу за вказаний період."""
    youtube = build('youtube', 'v3', developerKey=api_key)
    videos_data = []
    next_page_token = None

    # Конвертуємо дати в формат ISO 8601 для YouTube API
    published_after = start_date.isoformat() + "T00:00:00Z"
    # Додаємо один день до кінцевої дати, щоб включити весь день
    published_before = (end_date + timedelta(days=1)).isoformat() + "T00:00:00Z"

    try:
        while True:
            request = youtube.search().list(
                part='snippet',
                channelId=channel_id,
                maxResults=50,  # Максимум за один запит
                pageToken=next_page_token,
                type='video',
                order='date',
                publishedAfter=published_after,
                publishedBefore=published_before
            )
            response = request.execute()

            video_ids = []
            for item in response.get('items', []):
                if item.get('id', {}).get('kind') == 'youtube#video':
                    video_ids.append(item['id']['videoId'])

            if not video_ids:
                break

            video_details_request = youtube.videos().list(
                part="snippet,statistics,contentDetails",
                id=",".join(video_ids)
            )
            video_details_response = video_details_request.execute()

            # ... (код перед циклом for item in video_details_response.get('items', []):)
            for item in video_details_response.get('items', []):
                # --- МОДИФІКОВАНО: Отримання, парсинг та фільтрація за тривалістю ---
                duration_iso = item.get('contentDetails', {}).get('duration')

                if not duration_iso:
                    # st.caption(f"Пропущено відео без даних про тривалість: {item['snippet']['title']}") # Для відладки
                    continue  # Пропускаємо відео, якщо з якоїсь причини немає даних про тривалість

                video_duration_seconds = parse_iso8601_duration(duration_iso)

                # Встановлюємо мінімальну тривалість для "не-Shorts" відео в секундах.
                # Shorts офіційно до 120 секунд.
                # Значення 121 означає, що відео тривалістю 120 секунд буде відфільтроване.
                MIN_DURATION_FOR_REGULAR_VIDEO_SECONDS = 121

                if video_duration_seconds < MIN_DURATION_FOR_REGULAR_VIDEO_SECONDS:
                    # st.caption(f"Пропущено Shorts/коротке відео: {item['snippet']['title']} ({video_duration_seconds}s)") # Для відладки
                    continue  # Пропускаємо це відео (ймовірно, Shorts або дуже коротке)
                # --- КІНЕЦЬ МОДИФІКОВАНОГО БЛОКУ ---

                video_title = item['snippet']['title']
                video_description = item['snippet']['description']
                view_count = int(item.get('statistics', {}).get('viewCount', 0))
                published_at_str = item['snippet']['publishedAt']
                published_date = datetime.strptime(published_at_str, "%Y-%m-%dT%H:%M:%SZ").date()

                videos_data.append({
                    'id': item['id'],  # Це вже videoId
                    'title': video_title,
                    'description': video_description,
                    'views': view_count,
                    'published_at': published_date,
                    'duration_seconds': video_duration_seconds,  # Опціонально: додаємо тривалість у секундах
                    'category': "Не визначено"
                })
            # ... (код після циклу)

            next_page_token = response.get('nextPageToken')
            if not next_page_token:
                break

# Створюємо DataFrame з зібраних даних
        final_df = pd.DataFrame(videos_data)
        
        # --- ДОДАНО: Видалення дублікатів відео за їх 'id' ---
        if not final_df.empty and 'id' in final_df.columns:
            # keep='first' означає, що якщо є дублікати, залишиться перший зустрінутий екземпляр
            final_df.drop_duplicates(subset=['id'], keep='first', inplace=True)
        # --- КІНЕЦЬ ДОДАНОГО БЛОКУ ---
            
        return final_df
    except Exception as e:
        st.error(f"Помилка при отриманні даних з YouTube: {e}")
        # Повертаємо пустий DataFrame у випадку помилки, щоб додаток не "впав"
        return pd.DataFrame(columns=['id', 'title', 'description', 'views', 'published_at', 'category'])


@st.cache_data(ttl=86400)  # Кешуємо результат на добу
def categorize_video_gpt(title, description, categories_list):
    """
    Категоризує відео за допомогою GPT з деталізованими інструкціями та прикладами.
    """
    
    # Визначаємо уніфіковану назву для категорії "Різне"
    # Вона має бути присутня у categories_list
    default_other_category = "Різне" 
    if default_other_category not in categories_list:
        if categories_list: # Якщо список не порожній, беремо останню категорію як "Різне"
            default_other_category = categories_list[-1] 
        else: # Дуже малоймовірний випадок, коли список категорій порожній
            return "Категорія не визначена (список категорій порожній)"

    # Перевіряємо наявність OpenAI API ключа
    # Припускаємо, що OPENAI_API_KEY - це глобальна змінна або доступна в цьому контексті
    # Якщо OPENAI_API_KEY передається як аргумент, зміни відповідно
    if 'OPENAI_API_KEY' not in globals() or not OPENAI_API_KEY:
         st.error("Ключ OpenAI API не налаштовано для функції categorize_video_gpt.")
         return default_other_category

    description_snippet = description[:1500] if description else "" # Ліміт опису

    # Словник з описами категорій (АДАПТУЙ ПІД СВІЙ ФІНАЛЬНИЙ СПИСОК CATEGORIES)
    # Це має точно відповідати твоїм категоріям у списку CATEGORIES
    category_instructions = {
        "Танки": "Відео про танки (напр., Т-64, Leopard, Abrams), їх модифікації, бойове застосування, огляди, порівняння, танкові бої, знищення ворожих танків.",
        "Артилерія": "Відео про артилерійські системи (гаубиці, САУ як PzH 2000, Caesar, РСЗВ як HIMARS, Grad, міномети), їхню роботу, боєприпаси, тактику застосування.",
        "Авіація": "Відео про військові літаки (напр., Су-25, МіГ-29, F-16), гелікоптери (Мі-8, Мі-24, Apache), повітряні бої, роботу ППО по авіації ворога.",
        "Бронетехніка": "Відео про броньовані машини піхоти (БМП), бронетранспортери (БТР як M113, Stryker), бойові розвідувальні машини, MRAP та іншу легку і середню бронетехніку (окрім танків).",
        "Дрони": "Відео про розвідувальні та ударні безпілотники (БПЛА), FPV-дрони, їх розробку, виробництво, застосування для розвідки та ураження цілей, боротьбу з ворожими дронами (РЕБ). Включно з аналізом еволюції БПЛА.",
        "Піхота і гарячі напрямки": "Відео про дії піхотних підрозділів, штурмові операції, бої в містах та на відкритій місцевості, репортажі з передової, тактику піхоти, аналіз бойових дій на конкретних гарячих напрямках (напр., Бахмут, Авдіївка). Включно з відео про роботу снайперів у складі піхотних груп.",
        "Героїзм та унікальні історії військових, портретні репортажі": "Інтерв'ю з військовослужбовцями ЗСУ, розповіді про їхній особистий бойовий шлях, проявлений героїзм, унікальні подвиги, досвід перебування в полоні, реабілітацію після поранень, мотиваційні сюжети про конкретних бійців, їхні думки та почуття. Включно з історіями про волонтерів, медиків на фронті.",
        "Навчання": "Навчальні відео, інструкції з використання зброї та техніки, тактичної медицини (напр., накладання турнікету), військової підготовки, розбір тактичних прийомів, тренування бійців, поради щодо виживання.",
        "Огляди зразків озброєння": "Детальні огляди конкретних моделей стрілецької зброї (автомати, кулемети, гвинтівки), гранатометів, ПТРК, ПЗРК, їхні технічні характеристики, переваги та недоліки, поради щодо вибору та використання. Також сюди відносяться огляди іншого спорядження, наприклад, сухпайків.",
        "Новини, Стріми, Аналітика": "Щоденні або щотижневі зведення новин з фронту та навколовоєнної ситуації, прямі трансляції (стріми) з обговоренням актуальних подій, аналітичні огляди воєнно-політичної ситуації, підсумки тижня, обговорення міжнародної допомоги, заяв офіційних осіб.",
        "Різне": "Відео, які не підпадають чітко під жодну з перерахованих вище категорій." # Базовий опис для "Різне"
    }

    # Формуємо частину промпту з інструкціями, базуючись на categories_list
    instructions_for_prompt = "Описи категорій, з яких потрібно вибрати ОДНУ:\n"
    for cat_name in categories_list:
        if cat_name in category_instructions:
            instructions_for_prompt += f"- **{cat_name}**: {category_instructions[cat_name]}\n"
        elif cat_name == default_other_category: # Якщо це "Різне" і його немає в інструкціях
             instructions_for_prompt += f"- **{default_other_category}**: {category_instructions.get(default_other_category, 'Відео, які не підпадають під жодну з перерахованих вище категорій.')}\n"


    # Приклади для Few-shot learning (адаптуй за потреби)
    examples_for_prompt = """
Ось кілька прикладів правильної категоризації:
1. Назва: "Неймовірний бій Leopard 2 проти Т-90" -> Категорія: Танки
2. Назва: "Як працює HIMARS: детальний розбір" -> Категорія: Артилерія
3. Назва: "Історія пілота Су-25, який виконав 100 бойових вильотів" -> Категорія: Героїзм та унікальні історії військових, портретні репортажі
4. Назва: "FPV-дрон знищує ворожий склад боєприпасів" -> Категорія: Дрони
5. Назва: "Стрім з Бахмута: останні новини з передової" -> Категорія: Новини, Стріми, Аналітика
6. Назва: "Огляд автомата АК-74: переваги та недоліки" -> Категорія: Огляди зразків озброєння
7. Назва: "Перша допомога при кульовому пораненні: інструкція" -> Категорія: Навчання
8. Назва: "Чому не можна з'єднувати магазини скотчем?" -> Категорія: Навчання (або Огляди зразків озброєння, якщо фокус на зброї)
"""

    prompt = f"""
Тебе просять виступити в ролі експерта, який категоризує відео для YouTube-каналу "Армія TV" військової тематики.
Твоє завдання – проаналізувати НАЗВУ та ОПИС відео і віднести його до ОДНІЄЇ найбільш підходящої категорії з наданого списку.
Уважно прочитай описи кожної категорії та приклади, щоб зробити правильний вибір.

{instructions_for_prompt}

{examples_for_prompt}

Тепер проаналізуй наступне відео:
Назва відео: "{title}"
Опис відео (фрагмент): "{description_snippet}"

Доступні категорії (ти маєш повернути ОДНУ з цих назв, точно як написано):
{', '.join(categories_list)}

Категорія:
"""
    try:
        response = openai.chat.completions.create(
            model="gpt-4o-mini", 
            messages=[
                {"role": "system", "content": "Ти експерт-класифікатор відеоконтенту військової тематики. Твоя відповідь – це ТІЛЬКИ точна назва однієї категорії зі списку доступних категорій."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=50, 
            temperature=0.0 
        )
        category_response = response.choices[0].message.content.strip()
        
        # Очищення відповіді від можливих зайвих слів типу "Категорія: X"
        if ":" in category_response:
            category_response = category_response.split(":")[-1].strip()
        
        # Додаткове очищення, якщо GPT повертає щось типу "Категорія X" або "'Категорія X'"
        for cat_name_iter in categories_list:
            if cat_name_iter.lower() in category_response.lower(): # Шукаємо назву категорії у відповіді
                category_response = cat_name_iter # Використовуємо точну назву з нашого списку
                break


        # Перевірка, чи повернута категорія є однією з дозволених
        matched_category = None
        for cat_option in categories_list:
            if cat_option.lower() == category_response.lower(): # Точне співпадіння без урахування регістру
                matched_category = cat_option # Повертаємо категорію з правильним регістром з нашого списку
                break
        
        if matched_category:
            return matched_category
        else:
            # Якщо точного співпадіння немає, спробуємо знайти часткове як останній варіант
            # Це менш бажано, бо може призвести до помилок, якщо назви категорій схожі
            # for cat_option in categories_list:
            #     if cat_option.lower() in category_response.lower():
            #         # st.warning(f"Категорія '{category_response}' не знайдена точно, вибрано схожу: '{cat_option}' для відео '{title}'")
            #         return cat_option
            # st.warning(f"Категорія '{category_response}' не розпізнана для відео '{title}', встановлено '{default_other_category}'")
            return default_other_category # Якщо нічого не підійшло, повертаємо "Різне"
            
    except Exception as e:
        st.warning(f"Помилка OpenAI при категоризації відео '{title}': {e}")
        return default_other_category


# Функція для поглибленої аналітики категорії від GPT
# @st.cache_data(ttl=3600) # Можна кешувати, але аналітика може залежати від свіжих даних
def get_category_insights_gpt(category_name, videos_p1_df_cat, videos_p2_df_cat, avg_total_views_p1, avg_total_views_p2,
                              period1_dates, period2_dates):
    """Генерує аналітику для конкретної категорії за допомогою GPT."""
    if not OPENAI_API_KEY:
        return "Аналітика недоступна: OpenAI API ключ не налаштовано."

    def format_video_list_for_gpt(df, period_name, max_videos=5):
        if df is None or df.empty:
            return f"Дані за {period_name} в цій категорії відсутні або їх небагато.\n"

        # Сортуємо за переглядами, показуємо найпопулярніші
        df_sorted = df.sort_values(by='views', ascending=False).head(max_videos)

        list_str = f"Приклади відео та їх перегляди ({period_name}, до {max_videos} найпопулярніших):\n"
        if df_sorted.empty:
            return list_str + "- Відео в цій категорії та періоді не знайдено.\n"
        for _, row in df_sorted.iterrows():
            list_str += f"- \"{row['title']}\" (Перегляди: {row['views']:,})\n"
        return list_str

    cat_avg_views_p1 = videos_p1_df_cat['views'].mean() if not videos_p1_df_cat.empty else 0
    cat_avg_views_p2 = videos_p2_df_cat['views'].mean() if not videos_p2_df_cat.empty else 0

    prompt = f"""
    Ти – досвідчений аналітик YouTube-контенту каналу "Армія TV". Проаналізуй категорію "{category_name}".

    Період 1: {period1_dates[0].strftime('%Y-%m-%d')} - {period1_dates[1].strftime('%Y-%m-%d')}
    Період 2: {period2_dates[0].strftime('%Y-%m-%d')} - {period2_dates[1].strftime('%Y-%m-%d')}

    Загальні середні перегляди на каналі:
    - Період 1: {avg_total_views_p1:,.0f}
    - Період 2: {avg_total_views_p2:,.0f}

    Дані по категорії "{category_name}":
    - Сер. перегляди (Період 1): {cat_avg_views_p1:,.0f} (Кількість відео: {len(videos_p1_df_cat)})
    - Сер. перегляди (Період 2): {cat_avg_views_p2:,.0f} (Кількість відео: {len(videos_p2_df_cat)})
    {format_video_list_for_gpt(videos_p1_df_cat, "Період 1")}
    {format_video_list_for_gpt(videos_p2_df_cat, "Період 2")}

    Надай стислу, але змістовну аналітику для категорії "{category_name}" (максимум 150 слів):
    1.  **Стабільність та інтерес:** Чи стабільні перегляди всередині категорії? Чи викликає тема інтерес? Як змінився інтерес порівняно з попереднім періодом?
    2.  **Підгрупи/закономірності (опціонально):** Якщо помітно, чи є підтеми, що працюють краще/гірше (напр., в "Танках" - Leopard vs Т-72)?
    3.  **Порівняння з середнім по каналу:** Наскільки ефективна ця категорія порівняно із загальними показниками каналу?

    Відповідай українською мовою.
    """
    try:
        response = openai.chat.completions.create(
            model="gpt-4o-mini",  # Або "gpt-3.5-turbo" для економії, але якість може бути нижча
            messages=[
                {"role": "system",
                 "content": "Ти аналітик YouTube, що надає стислі та змістовні висновки по категоріях."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=350,  # Налаштуй за потребою
            temperature=0.4
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        st.warning(f"Помилка OpenAI при аналізі категорії '{category_name}': {e}")
        return f"Не вдалося отримати аналітику для категорії '{category_name}' через помилку API."


# Функція для форматування посилання на відео
def create_youtube_link(video_id, title):
    """Створює Markdown посилання на відео YouTube."""
    video_id_str = str(video_id)
    return f"[{title}](https://www.youtube.com/watch?v={video_id_str})"

# Функція для генерації загальних підсумків
# @st.cache_data(ttl=3600)
def get_overall_summary_gpt(all_categories_stats_merged, avg_total_p1, avg_total_p2, period1_str, period2_str):
    """Генерує загальні висновки та рекомендації на основі всіх даних."""
    if not OPENAI_API_KEY:
        return "Підсумки недоступні: OpenAI API ключ не налаштовано."

    categories_data_str = "Зведена статистика по категоріях:\n"
    if all_categories_stats_merged.empty:
        categories_data_str += "Дані по категоріях відсутні для аналізу.\n"
    else:
        for _, row in all_categories_stats_merged.iterrows():
            categories_data_str += f"- Категорія: {row['category']}\n"
            categories_data_str += f"  Період 1: Відео: {int(row['count_p1'])}, Сер.перегляди: {int(row['avg_views_p1']):,}\n"
            categories_data_str += f"  Період 2: Відео: {int(row['count_p2'])}, Сер.перегляди: {int(row['avg_views_p2']):,}\n"

            # Динаміка
            avg1, avg2 = row['avg_views_p1'], row['avg_views_p2']
            if avg1 > 0 and avg2 > 0:
                change = ((avg2 - avg1) / avg1) * 100
                categories_data_str += f"  Динаміка сер. переглядів: {change:+.1f}%\n\n"
            elif avg2 > 0:
                categories_data_str += f"  Динаміка сер. переглядів: З'явилися нові перегляди.\n\n"
            else:
                categories_data_str += f"  Динаміка сер. переглядів: Немає даних для порівняння.\n\n"

    prompt = f"""
    Ти – головний контент-стратег YouTube-каналу "Армія TV". Проаналізуй дані за два періоди.
    Період 1: {period1_str}
    Період 2: {period2_str}

    Загальні середні перегляди на каналі:
    - Період 1: {avg_total_p1:,.0f}
    - Період 2: {avg_total_p2:,.0f}

    {categories_data_str}

    Твоє завдання – зробити розгорнутий, але чіткий висновок (близько 250-350 слів), який включатиме:
    1.  **Ключові тенденції:** Які загальні зміни відбулися в ефективності контенту між періодами?
    2.  **Успішні сюжети/характеристики:** Визнач риси, притаманні успішним сюжетам. Наприклад: "бронетехніка західного зразка і українська бронетехніка; трофейна зброя і техніка; розпаковка техніки, її начинка; авіація; бої і динаміка; ексклюзивність". Можеш використовувати ці приклади, якщо вони підтверджуються даними, або запропонуй свої.
    3.  **Неуспішні сюжети/характеристики:** Визнач риси, притаманні неуспішним сюжетам. Наприклад: "радянська техніка, особливо РСЗВ; дрони (якщо це так); портретні історії про видатних бійців (якщо це так); снайпери". Можеш використовувати ці приклади або запропонуй свої.
    4.  **Стратегічні рекомендації:** Які 2-3 конкретні поради ти можеш дати команді для покращення контент-плану та підвищення ефективності відео?

    Будь об'єктивним, спирайся на надані цифри, але також роби обґрунтовані припущення щодо причинно-наслідкових зв'язків. Відповідай українською мовою.
    """
    try:
        response = openai.chat.completions.create(
            model="gpt-4o",  # Ця модель найкраще підходить для таких завдань
            messages=[
                {"role": "system", "content": "Ти головний контент-стратег, що готує фінальний звіт з рекомендаціями."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=800,  # Більше токенів для детального звіту
            temperature=0.5
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        st.error(f"Помилка OpenAI при генерації підсумків: {e}")
        return "Не вдалося згенерувати підсумки через помилку API."

if not YOUTUBE_API_KEY:
    st.error("Помилка: Ключ YouTube API не надано у файлі config_keys.py.")
    st.stop()


# ФУНКЦІЯ КНОПКИ

def generate_report_markdown(
        period1_label, period2_label,
        total_videos_p1, avg_views_p1,
        total_videos_p2, avg_views_p2,
        delta_avg_views_overall, delta_percent_overall,  # Ці змінні для загальної динаміки
        merged_category_stats_df,  # DataFrame зі статистикою по категоріях
        category_insights_dict,  # Словник, де ключ - назва категорії, значення - аналітика GPT
        overall_summary_gpt  # Загальний звіт GPT
):
    """Генерує текстовий звіт у форматі Markdown."""

    report_content = f"# Звіт з аналізу YouTube-каналу 'Армія TV'\n\n"
    report_content += f"Дата генерації звіту: {date.today().strftime('%d.%m.%Y')}\n\n"  # Додаємо дату генерації
    report_content += f"## Аналізовані Періоди\n"
    report_content += f"- **Період 1:** {period1_label}\n"
    report_content += f"- **Період 2:** {period2_label}\n\n"

    report_content += f"## Загальна Статистика Переглядів\n"
    report_content += f"### Період 1 ({period1_label})\n"
    report_content += f"- Всього відео (що пройшли фільтрацію): {total_videos_p1}\n"
    report_content += f"- Середня кількість переглядів на відео: {avg_views_p1:,.0f}\n\n"

    report_content += f"### Період 2 ({period2_label})\n"
    report_content += f"- Всього відео (що пройшли фільтрацію): {total_videos_p2}\n"
    report_content += f"- Середня кількість переглядів на відео: {avg_views_p2:,.0f}\n\n"

    # Динаміка загальних переглядів
    if total_videos_p1 > 0 and total_videos_p2 > 0 and avg_views_p1 > 0:
        report_content += f"**Динаміка середніх переглядів (Період 2 vs Період 1):** {delta_avg_views_overall:,.0f} ({delta_percent_overall:+.1f}%)\n\n"
    elif total_videos_p1 == 0 and total_videos_p2 > 0:
        report_content += f"**Динаміка середніх переглядів (Період 2 vs Період 1):** Дані за Період 1 відсутні, порівняння неможливе.\n\n"
    elif total_videos_p1 > 0 and total_videos_p2 == 0:
        report_content += f"**Динаміка середніх переглядів (Період 2 vs Період 1):** Дані за Період 2 відсутні, порівняння неможливе.\n\n"
    else:
        report_content += f"**Динаміка середніх переглядів (Період 2 vs Період 1):** Недостатньо даних для розрахунку динаміки.\n\n"

    report_content += f"## Детальний Аналіз за Категоріями\n"
    if not merged_category_stats_df.empty:
        for index, row_cat in merged_category_stats_df.iterrows():
            report_content += f"### Категорія: {row_cat['category']}\n"
            report_content += f"- **Період 1:** Відео: {int(row_cat['count_p1'])}, Ø Перегляди: {int(row_cat['avg_views_p1']):,}\n"
            report_content += f"- **Період 2:** Відео: {int(row_cat['count_p2'])}, Ø Перегляди: {int(row_cat['avg_views_p2']):,}\n"

            # Динаміка для категорії
            avg1_cat = int(row_cat['avg_views_p1'])
            avg2_cat = int(row_cat['avg_views_p2'])
            count1_cat = int(row_cat['count_p1'])
            count2_cat = int(row_cat['count_p2'])

            if count1_cat > 0 and count2_cat > 0 and avg1_cat > 0:
                cat_delta_avg = avg2_cat - avg1_cat
                cat_delta_perc = (cat_delta_avg / avg1_cat) * 100 if avg1_cat != 0 else 0
                report_content += f"  - Динаміка Ø переглядів категорії: {cat_delta_avg:,.0f} ({cat_delta_perc:+.1f}%)\n"
            elif count2_cat > 0 and count1_cat == 0:
                report_content += f"  - Динаміка Ø переглядів категорії: Нова активність у Періоді 2.\n"
            elif count1_cat > 0 and count2_cat == 0:
                report_content += f"  - Динаміка Ø переглядів категорії: Активність була лише у Періоді 1.\n"
            else:
                report_content += f"  - Динаміка Ø переглядів категорії: Недостатньо даних.\n"

            if row_cat['category'] in category_insights_dict and category_insights_dict[row_cat['category']]:
                report_content += f"\n  **Висновки GPT для категорії \"{row_cat['category']}\":**\n"
                # Замінюємо переноси рядків на такі, що працюють в Markdown для багаторядкових блоків
                insight_text = str(category_insights_dict[row_cat['category']]).replace('\n', '\n  ')
                report_content += f"  {insight_text}\n\n"
            else:
                report_content += f"  Висновки GPT для категорії \"{row_cat['category']}\" відсутні.\n\n"
    else:
        report_content += "Дані по категоріях відсутні.\n\n"

    report_content += f"## Загальні Підсумки та Рекомендації від GPT\n"
    if overall_summary_gpt and overall_summary_gpt.strip() and overall_summary_gpt != "Недостатньо даних для генерації загальних підсумків.":
        report_content += f"{overall_summary_gpt}\n"
    else:
        report_content += "Загальні підсумки та рекомендації від GPT не були згенеровані (або були порожніми).\n"

    return report_content




# --- Основна логіка додатку ---

if not YOUTUBE_API_KEY:
    st.error("Помилка: Ключ YouTube API не надано у файлі config_keys.py.")
    st.stop()
if not OPENAI_API_KEY:
    st.error("Помилка: Ключ OpenAI API не надано у файлі config_keys.py.")
    st.stop()

# Функціонал 1: Вибір двох періодів
st.sidebar.header("🗓️ Виберіть періоди для аналізу")
today = date.today()
# Знаходимо перший день минулого місяця
# Спочатку отримуємо перший день поточного місяця
first_day_current_month = today.replace(day=1)
# Потім віднімаємо один день, щоб отримати останній день минулого місяця
last_day_previous_month = first_day_current_month - timedelta(days=1)
# І встановлюємо день на 1, щоб отримати перший день минулого місяця
first_day_previous_month = last_day_previous_month.replace(day=1)

# Період 1 (зліва)
st.sidebar.subheader("Період 1")
date_start_1 = st.sidebar.date_input(
    "Дата початку (Період 1)",
    first_day_previous_month,  # За замовчуванням - початок минулого місяця
    max_value=today,
    key="p1_start"
)
date_end_1 = st.sidebar.date_input(
    "Дата кінця (Період 1)",
    last_day_previous_month,  # За замовчуванням - кінець минулого місяця
    max_value=today,
    key="p1_end"
)

# Період 2 (справа)
st.sidebar.subheader("Період 2")
date_start_2 = st.sidebar.date_input(
    "Дата початку (Період 2)",
    first_day_current_month,  # За замовчуванням - початок поточного місяця
    max_value=today,
    key="p2_start"
)
date_end_2 = st.sidebar.date_input(
    "Дата кінця (Період 2)",
    today,  # За замовчуванням - сьогодні
    max_value=today,
    key="p2_end"
)

# Кнопка для запуску аналізу
if st.sidebar.button("🚀 Почати аналіз", type="primary"):
    if date_start_1 > date_end_1:
        st.error("Період 1: Дата початку не може бути пізніше дати кінця.")
    elif date_start_2 > date_end_2:
        st.error("Період 2: Дата початку не може бути пізніше дати кінця.")
    else:
        st.info(f"🔄 Збираємо та аналізуємо дані... Це може зайняти деякий час, особливо якщо періоди великі.")

        # Отримання даних для періодів
        with st.spinner('Завантаження даних для Періоду 1...'):
            videos_p1_df = get_channel_videos(YOUTUBE_API_KEY, CHANNEL_ID, date_start_1, date_end_1)
        with st.spinner('Завантаження даних для Періоду 2...'):
            videos_p2_df = get_channel_videos(YOUTUBE_API_KEY, CHANNEL_ID, date_start_2, date_end_2)

        if videos_p1_df.empty and videos_p2_df.empty:
            st.warning("Не знайдено відео за обрані періоди. Спробуйте інші дати або перевірте CHANNEL_ID.")
            st.stop()

        # Функціонал 2: Середні перегляди та динаміка
        st.header("📊 Загальна статистика переглядів")
        col_stats1, col_stats2 = st.columns(2)

        avg_views_p1 = videos_p1_df['views'].mean() if not videos_p1_df.empty else 0
        total_videos_p1 = len(videos_p1_df)
        avg_views_p2 = videos_p2_df['views'].mean() if not videos_p2_df.empty else 0
        total_videos_p2 = len(videos_p2_df)

        period1_label = f"{date_start_1.strftime('%d.%m.%Y')} - {date_end_1.strftime('%d.%m.%Y')}"
        period2_label = f"{date_start_2.strftime('%d.%m.%Y')} - {date_end_2.strftime('%d.%m.%Y')}"

        with col_stats1:
            st.subheader(f"Період 1: {period1_label}")
            st.metric(label="Всього відео", value=f"{total_videos_p1}")
            st.metric(label="Ø Переглядів на відео", value=f"{avg_views_p1:,.0f}")

        with col_stats2:
            st.subheader(f"Період 2: {period2_label}")
            st.metric(label="Всього відео", value=f"{total_videos_p2}")
            st.metric(label="Ø Переглядів на відео", value=f"{avg_views_p2:,.0f}")

            # Візуалізація динаміки
            delta_avg_views_overall = 0  # Ініціалізуємо для подальшого використання у звіті
            delta_percent_overall = 0.0

            if total_videos_p1 > 0 and total_videos_p2 > 0 and avg_views_p1 > 0:
                delta_avg_views_overall = avg_views_p2 - avg_views_p1
                delta_percent_overall = (delta_avg_views_overall / avg_views_p1) * 100 if avg_views_p1 else 0
                st.metric(label="Зміна Ø переглядів порівняно з Періодом 1", value=f"{delta_avg_views_overall:,.0f}",
                          delta=f"{delta_percent_overall:.1f}%")
            elif total_videos_p2 > 0 and total_videos_p1 == 0:  # Дані є тільки в другому періоді
                st.info("Порівняння динаміки неможливе (немає даних за Період 1, але є за Період 2).")
            elif total_videos_p1 > 0 and total_videos_p2 == 0:  # Дані є тільки в першому періоді
                st.info("Порівняння динаміки неможливе (немає даних за Період 2, але є за Період 1).")
            else:  # Немає даних в обох або тільки в одному, але avg_views_p1 = 0
                st.info("Недостатньо даних для порівняння динаміки.")

        # Функціонал 3: Категоризація відео
        st.header("🗂️ Аналіз за категоріями")

        videos_p1_categorized_df = videos_p1_df.copy()
        videos_p2_categorized_df = videos_p2_df.copy()

        # Зберігаємо середні загальні перегляди в session_state для використання в get_category_insights_gpt
        st.session_state.avg_views_period1 = avg_views_p1
        st.session_state.avg_views_period2 = avg_views_p2

        if not videos_p1_categorized_df.empty:
            st.subheader(f"Категоризація відео за Період 1 ({period1_label})")
            progress_bar_1 = st.progress(0.0) # Ініціалізуємо з 0.0 (float)
            status_text_1 = st.empty()
            num_videos_p1 = len(videos_p1_categorized_df) # Отримуємо загальну кількість один раз
            
            # Використовуємо enumerate для отримання послідовного індексу 'idx'
            for idx, (df_index, row) in enumerate(videos_p1_categorized_df.iterrows()):
                category = categorize_video_gpt(row['title'], row['description'], CATEGORIES)
                videos_p1_categorized_df.loc[df_index, 'category'] = category # Використовуємо оригінальний індекс df_index для .loc
                time.sleep(0.1)

                # Розраховуємо відсоток на основі послідовного індексу 'idx'
                progress_percentage = (idx + 1) / num_videos_p1
                # Додаткова гарантія, що значення не перевищить 1.0
                progress_bar_1.progress(min(progress_percentage, 1.0)) 
                status_text_1.text(f"Обробка відео {idx + 1}/{num_videos_p1}...")
            status_text_1.success(f"Категоризація відео за Період 1 завершена!")
            progress_bar_1.empty()
# ...
        if not videos_p2_categorized_df.empty:
            st.subheader(f"Категоризація відео за Період 2 ({period2_label})")
            progress_bar_2 = st.progress(0.0) # Ініціалізуємо з 0.0 (float)
            status_text_2 = st.empty()
            num_videos_p2 = len(videos_p2_categorized_df) # Отримуємо загальну кількість один раз

            # Використовуємо enumerate для отримання послідовного індексу 'idx'
            for idx, (df_index, row) in enumerate(videos_p2_categorized_df.iterrows()):
                category = categorize_video_gpt(row['title'], row['description'], CATEGORIES)
                videos_p2_categorized_df.loc[df_index, 'category'] = category # Використовуємо оригінальний індекс df_index для .loc
                time.sleep(0.1)

                # Розраховуємо відсоток на основі послідовного індексу 'idx'
                progress_percentage = (idx + 1) / num_videos_p2
                # Додаткова гарантія, що значення не перевищить 1.0
                progress_bar_2.progress(min(progress_percentage, 1.0))
                status_text_2.text(f"Обробка відео {idx + 1}/{num_videos_p2}...")
            status_text_2.success(f"Категоризація відео за Період 2 завершена!")
            progress_bar_2.empty()
# ...


        # 3.1: Кількість відео та середні перегляди по категоріях + динаміка
        def get_category_stats_df(df):
            if df.empty or 'category' not in df.columns:
                return pd.DataFrame(columns=['category', 'video_count', 'average_views'])
            stats = df.groupby('category').agg(
                video_count=('id', 'count'),
                average_views=('views', 'mean')
            ).reset_index()
            stats['average_views'] = pd.to_numeric(stats['average_views'], errors='coerce').fillna(0)
            stats['average_views'] = stats['average_views'].round(0).astype(int)
            return stats


        category_stats_p1 = get_category_stats_df(videos_p1_categorized_df)
        category_stats_p2 = get_category_stats_df(videos_p2_categorized_df)

        merged_category_stats = pd.merge(
            category_stats_p1.rename(columns={'video_count': 'count_p1', 'average_views': 'avg_views_p1'}),
            category_stats_p2.rename(columns={'video_count': 'count_p2', 'average_views': 'avg_views_p2'}),
            on='category',
            how='outer'
        ).fillna(0)

        for col in ['count_p1', 'avg_views_p1', 'count_p2', 'avg_views_p2']:
            merged_category_stats[col] = pd.to_numeric(merged_category_stats[col], errors='coerce').fillna(0).astype(
                int)

        category_insights_for_report = {}  # Для майбутнього експорту

        if not merged_category_stats.empty:
            st.subheader("Детальна статистика по категоріях")

            try:
                merged_category_stats['category_order'] = merged_category_stats['category'].apply(
                    lambda x: CATEGORIES.index(x) if x in CATEGORIES else len(CATEGORIES)
                )
                merged_category_stats = merged_category_stats.sort_values(by='category_order').drop(
                    columns=['category_order'])
            except ValueError as e:
                st.warning(
                    f"Помилка при сортуванні категорій: {e}. Можливо, GPT повернув категорію, якої немає у списку CATEGORIES.")
                merged_category_stats = merged_category_stats.sort_values(by='category')

            for index, row_cat in merged_category_stats.iterrows():
                st.markdown(f"--- \n#### Категорія: {row_cat['category']}")
                cat_col1, cat_col2, cat_col3 = st.columns([2, 2, 3])

                with cat_col1:
                    st.metric(label=f"Відео (Період 1)", value=f"{row_cat['count_p1']}")
                    st.metric(label=f"Ø Перегляди (Період 1)", value=f"{row_cat['avg_views_p1']:,}")

                with cat_col2:
                    st.metric(label=f"Відео (Період 2)", value=f"{row_cat['count_p2']}")
                    st.metric(label=f"Ø Перегляди (Період 2)", value=f"{row_cat['avg_views_p2']:,}")

                    if row_cat['count_p1'] > 0 and row_cat['count_p2'] > 0 and row_cat['avg_views_p1'] > 0:
                        cat_delta_avg = row_cat['avg_views_p2'] - row_cat['avg_views_p1']
                        cat_delta_perc = (cat_delta_avg / row_cat['avg_views_p1']) * 100 if row_cat[
                                                                                                'avg_views_p1'] != 0 else 0
                        st.metric(label="Зміна Ø переглядів", value=f"{cat_delta_avg:,.0f}",
                                  delta=f"{cat_delta_perc:.1f}%")
                    elif row_cat['count_p2'] > 0 and row_cat['count_p1'] == 0:
                        st.markdown("<p style='font-size:small; color:gray;'>Нова активність у Періоді 2</p>",
                                    unsafe_allow_html=True)
                    elif row_cat['count_p1'] > 0 and row_cat['count_p2'] == 0:
                        st.markdown("<p style='font-size:small; color:gray;'>Активність була лише у Періоді 1</p>",
                                    unsafe_allow_html=True)
                # --- КІНЕЦЬ БЛОКУ with cat_col2 ---
                # --- ОСЬ ТУТ МАЄ БУТИ ФІЛЬТРАЦІЯ ---
                cat_videos_p1_df_filtered = pd.DataFrame() # Ініціалізуємо як порожній DataFrame
if not videos_p1_categorized_df.empty and 'category' in videos_p1_categorized_df.columns:
    try:
        cat_videos_p1_df_filtered = videos_p1_categorized_df[
            videos_p1_categorized_df['category'] == row_cat['category']
        ]
    except Exception as e:
        st.warning(f"Помилка при фільтрації відео Періоду 1 для категорії '{row_cat['category']}': {e}")
        # Залишаємо cat_videos_p1_df_filtered порожнім, оскільки його вже ініціалізовано як порожній
else:
    if videos_p1_categorized_df.empty:
        pass # DataFrame порожній, cat_videos_p1_df_filtered залишається порожнім
    elif 'category' not in videos_p1_categorized_df.columns:
        st.warning(f"Стовпець 'category' відсутній у даних Періоду 1 для аналізу категорії '{row_cat['category']}'.")
        # cat_videos_p1_df_filtered залишається порожнім

cat_videos_p2_df_filtered = pd.DataFrame() # Ініціалізуємо як порожній DataFrame
if not videos_p2_categorized_df.empty and 'category' in videos_p2_categorized_df.columns:
    try:
        cat_videos_p2_df_filtered = videos_p2_categorized_df[
            videos_p2_categorized_df['category'] == row_cat['category']
        ]
    except Exception as e:
        st.warning(f"Помилка при фільтрації відео Періоду 2 для категорії '{row_cat['category']}': {e}")
        # Залишаємо cat_videos_p2_df_filtered порожнім
else:
    if videos_p2_categorized_df.empty:
        pass # DataFrame порожній, cat_videos_p2_df_filtered залишається порожнім
    elif 'category' not in videos_p2_categorized_df.columns:
        st.warning(f"Стовпець 'category' відсутній у даних Періоду 2 для аналізу категорії '{row_cat['category']}'.")
        # cat_videos_p2_df_filtered залишається порожнім
        
                # --- КІНЕЦЬ БЛОКУ ФІЛЬТРАЦІЇ ---
                # Тепер with cat_col3: (такий самий рівень відступу)

                with cat_col3:
                    with st.spinner(f"Аналіз категорії '{row_cat['category']}' від GPT..."):
                        avg_total_p1_for_cat_insights = st.session_state.get('avg_views_period1', 0)
                        avg_total_p2_for_cat_insights = st.session_state.get('avg_views_period2', 0)

                        insights = get_category_insights_gpt(
                            row_cat['category'],
                            cat_videos_p1_df_filtered,
                            cat_videos_p2_df_filtered,
                            avg_total_p1_for_cat_insights,
                            avg_total_p2_for_cat_insights,
                            (date_start_1, date_end_1),
                            (date_start_2, date_end_2)
                        )
                        st.markdown(f"**Висновки GPT для категорії \"{row_cat['category']}\":**")
                        st.caption(insights)
                        category_insights_for_report[row_cat['category']] = insights
                        time.sleep(0.2)
                # --- ТЕПЕР ЕКСПАНДЕР (такий самий рівень відступу) ---
                # Визначаємо, чи є відео в цій категорії хоча б за один період
                has_videos_in_category_p1 = not cat_videos_p1_df_filtered.empty
                has_videos_in_category_p2 = not cat_videos_p2_df_filtered.empty

                total_videos_in_category_for_expander = 0
                if has_videos_in_category_p1:
                    total_videos_in_category_for_expander += len(cat_videos_p1_df_filtered)
                if has_videos_in_category_p2:
                    total_videos_in_category_for_expander += len(cat_videos_p2_df_filtered)

                expander_label = f"📄 Переглянути відео в категорії '{row_cat['category']}' ({total_videos_in_category_for_expander} відео)"
                if total_videos_in_category_for_expander == 0:
                    expander_label = f"📄 Відео в категорії '{row_cat['category']}' відсутні"

                with st.expander(expander_label):

                    # Відео за Період 1
                    st.markdown(f"**Відео за Період 1 ({period1_label}):**")
                    if has_videos_in_category_p1:
                        for _, video_row in cat_videos_p1_df_filtered.sort_values(by='views', ascending=False).iterrows():
                            video_id_val = video_row['id']
                            video_title = video_row['title']
                            video_views = video_row['views']
                            link = create_youtube_link(video_id_val, video_title)
                            st.markdown(f"- {link} (Перегляди: {video_views:,})")
                    else:
                        st.caption("Відео за цей період у даній категорії відсутні.")

                    st.markdown("---")

                    # Відео за Період 2
                    st.markdown(f"**Відео за Період 2 ({period2_label}):**")
                    if has_videos_in_category_p2:
                        for _, video_row in cat_videos_p2_df_filtered.sort_values(by='views', ascending=False).iterrows():
                            video_id_val = video_row['id']
                            video_title = video_row['title']
                            video_views = video_row['views']
                            link = create_youtube_link(video_id_val, video_title)
                            st.markdown(f"- {link} (Перегляди: {video_views:,})")
                    else:
                        st.caption("Відео за цей період у даній категорії відсутні.")
                # --- КІНЕЦЬ БЛОКУ ЕКСПАНДЕРА ---
        else:
            st.info("Немає даних для відображення статистики по категоріях після категоризації.")

        # Функціонал 4: Підсумки від GPT
        st.header("🏆 Загальні підсумки та рекомендації")
        overall_summary_report_data = "Недостатньо даних для генерації загальних підсумків."
        if not merged_category_stats.empty:
            with st.spinner("GPT готує фінальний звіт... Це може зайняти хвилину-дві."):
                overall_summary_report_data = get_overall_summary_gpt(
                    merged_category_stats,
                    avg_views_p1,
                    avg_views_p2,
                    period1_label,
                    period2_label
                )
                st.markdown(overall_summary_report_data)
        else:
            st.warning("Недостатньо категоризованих даних для генерації загальних підсумків.")

        st.success("Аналіз завершено!")
        # app.py (продовження)
        # ... (код всередині if st.sidebar.button(...), до st.success("Аналіз завершено!"))

        # --- КНОПКА ЕКСПОРТУ ЗВІТУ ---
        # Переконуємося, що всі необхідні змінні для звіту існують і мають значення.
        # Змінні: period1_label, period2_label, total_videos_p1, avg_views_p1,
        # total_videos_p2, avg_views_p2, delta_avg_views_overall, delta_percent_overall,
        # merged_category_stats, category_insights_for_report, overall_summary_report_data
        # вже мають бути визначені на цьому етапі виконання коду.

        # Формуємо назву каналу для звіту (можна взяти з CHANNEL_ID або задати вручну)
        # Для прикладу, якщо CHANNEL_ID це "UCk_9267pA5M4Y3Z_Yj_1_9Q", то це "Військове телебачення України"
        # Ти можеш задати назву каналу як константу на початку файлу, якщо потрібно.
        # Тут я просто залишу "ArmiyaTV" для прикладу.
        channel_name_for_report = "ArmyTV_AInalitics"

        # Перевірка, чи основні дані для звіту не порожні.
        # (category_insights_for_report може бути порожнім, якщо немає категорій,
        #  overall_summary_report_data може містити повідомлення про недостатність даних)
        if 'merged_category_stats' in locals() and not merged_category_stats.empty:
            st.sidebar.markdown("---")
            st.sidebar.header("📥 Експорт Звіту")

            report_str_for_download = generate_report_markdown(
                period1_label, period2_label,
                total_videos_p1, avg_views_p1,
                total_videos_p2, avg_views_p2,
                delta_avg_views_overall,
                delta_percent_overall,
                merged_category_stats,
                category_insights_for_report,
                overall_summary_report_data
            )

            current_date_str = date.today().strftime("%Y-%m-%d")  # Використовуємо поточну дату
            report_filename = f"youtube_analysis_{channel_name_for_report}_{current_date_str}.md"

            st.sidebar.download_button(
                label="📄 Завантажити звіт (.md)",
                data=report_str_for_download.encode('utf-8'),  # Кодуємо в UTF-8 для коректного збереження кирилиці
                file_name=report_filename,
                mime="text/markdown"
            )
        else:
            # Якщо merged_category_stats порожній, кнопка експорту не буде показана,
            # або можна вивести повідомлення на бічній панелі.
            st.sidebar.info("Дані для генерації звіту відсутні (немає статистики по категоріях).")

else:
    st.info("☝️ Будь ласка, виберіть періоди та натисніть кнопку 'Почати аналіз' на бічній панелі.")

st.sidebar.markdown("---")
st.sidebar.markdown("Аналітичний агент для YouTube.")
