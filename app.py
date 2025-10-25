import streamlit as st
import requests
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from collections import Counter
import time
import numpy as np
from datetime import datetime
import io

# Настройка страницы
st.set_page_config(
    page_title="Journal Quality Analysis",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded"
)

# API endpoints
CROSSREF_BASE_URL = "https://api.crossref.org/works"
OPENALEX_BASE_URL = "https://api.openalex.org/works"

def calculate_impact_factor_years():
    """Определяет годы для расчета импакт-фактора на основе текущей даты"""
    current_date = datetime.now()
    current_year = current_date.year
    current_month = current_date.month
    
    # Согласно стандартной практике: IF рассчитывается за предыдущий год
    # если текущий месяц январь, то рассчитываем за текущий год-1
    if current_month == 1:  # Январь
        citation_year = current_year - 1  # Цитирования за предыдущий год
        publication_years = [current_year - 3, current_year - 2]  # Статьи за 2 предыдущих года
    else:
        citation_year = current_year - 1  # Цитирования за предыдущий год
        publication_years = [current_year - 3, current_year - 2]  # Статьи за 2 предыдущих года
    
    return citation_year, publication_years

@st.cache_data(show_spinner=False, ttl=3600)
def fetch_crossref_articles(issn, from_date, until_date):
    """Fetch articles from Crossref API with cursor-based pagination"""
    items = []
    cursor = "*"
    progress_bar = st.progress(0)
    status_text = st.empty()

    while True:
        params = {
            'filter': f'issn:{issn},from-pub-date:{from_date},until-pub-date:{until_date}',
            'rows': 1000,
            'cursor': cursor,
            'mailto': 'example@email.com'
        }
        try:
            resp = requests.get(CROSSREF_BASE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            message = data['message']
            items.extend(message['items'])
            cursor = message.get('next-cursor')
            
            status_text.text(f" Retrieved {len(items)} articles...")
            if len(items) > 0:
                progress_bar.progress(min(len(items) / 1000, 1.0))
                
            if not cursor or len(message['items']) == 0:
                break
        except Exception as e:
            st.error(f"Error fetching Crossref data: {e}")
            break

    progress_bar.empty()
    status_text.empty()
    return items

@st.cache_data(show_spinner=False, ttl=3600)
def get_openalex_work_by_doi(doi):
    """Get work data from OpenAlex by DOI"""
    if doi == 'N/A':
        return None
    
    try:
        # Normalize DOI for OpenAlex
        if not doi.startswith('https://doi.org/'):
            doi_url = f"https://doi.org/{doi}"
        else:
            doi_url = doi
        
        url = f"{OPENALEX_BASE_URL}/{doi_url}"
        resp = requests.get(url, timeout=10)
        
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 404:
            return None
        else:
            st.warning(f"OpenAlex API error for {doi}: {resp.status_code}")
            return None
    except Exception as e:
        st.warning(f"Error fetching OpenAlex data for {doi}: {e}")
        return None

def get_citing_articles_openalex(doi, progress_bar=None, status_text=None):
    """Get ALL citing DOIs for a given article through OpenAlex - NO LIMITS"""
    citing_dois = []
    
    if doi == 'N/A':
        return citing_dois

    # Get work data first
    work_data = get_openalex_work_by_doi(doi)
    if not work_data:
        return citing_dois

    cited_by_count = work_data.get('cited_by_count', 0)
    if status_text:
        status_text.text(f"    Article has {cited_by_count} citations")

    if cited_by_count > 0:
        # Get list of ALL citing works with pagination
        page = 1
        per_page = 200  # Maximum per page
        cited_by_url = f"https://api.openalex.org/works?filter=cites:{work_data['id']}&per-page={per_page}"
        
        while cited_by_url:
            try:
                if status_text:
                    status_text.text(f"   ↳ Fetching citation page {page}...")
                response_cited = requests.get(cited_by_url, timeout=20)
                if response_cited.status_code == 200:
                    cited_data = response_cited.json()
                    results = cited_data.get('results', [])
                    
                    for work in results:
                        # Extract DOI from citing work
                        if work.get('doi'):
                            citing_doi = work['doi']
                            if citing_doi.startswith('https://doi.org/'):
                                citing_doi = citing_doi[16:]
                            citing_dois.append(citing_doi)
                        elif work.get('ids', {}).get('doi'):
                            citing_doi = work['ids']['doi']
                            if citing_doi.startswith('https://doi.org/'):
                                citing_doi = citing_doi[16:]
                            citing_dois.append(citing_doi)
                    
                    if status_text:
                        status_text.text(f"    Page {page}: found {len(results)} citing articles")
                    
                    # Update progress
                    if progress_bar and cited_by_count > 0:
                        progress = min(page * per_page / cited_by_count, 1.0)
                        progress_bar.progress(progress)
                    
                    # Check for next page
                    cited_by_url = cited_data.get('meta', {}).get('next_page')
                    if cited_by_url:
                        page += 1
                        time.sleep(0.3)  # Be polite to API
                    else:
                        break
                else:
                    st.warning(f"    Error fetching citations page {page}: {response_cited.status_code}")
                    break
            except Exception as e:
                st.warning(f"    Error in pagination for {doi}: {e}")
                break

    if status_text:
        status_text.text(f"    Total citing articles collected: {len(citing_dois)}")
    return citing_dois

def get_citing_articles_openalex_with_years(doi, target_citation_year, progress_bar=None, status_text=None):
    """Get ALL citing DOIs for a given article through OpenAlex с фильтрацией по году цитирования"""
    citing_articles = []  # Будем хранить DOI и год цитирования
    
    if doi == 'N/A':
        return citing_articles

    # Get work data first
    work_data = get_openalex_work_by_doi(doi)
    if not work_data:
        return citing_articles

    cited_by_count = work_data.get('cited_by_count', 0)
    if status_text:
        status_text.text(f"    Article has {cited_by_count} citations")

    if cited_by_count > 0:
        # Get list of ALL citing works with pagination
        page = 1
        per_page = 200  # Maximum per page
        cited_by_url = f"https://api.openalex.org/works?filter=cites:{work_data['id']}&per-page={per_page}"
        
        while cited_by_url:
            try:
                if status_text:
                    status_text.text(f"   ↳ Fetching citation page {page}...")
                response_cited = requests.get(cited_by_url, timeout=20)
                if response_cited.status_code == 200:
                    cited_data = response_cited.json()
                    results = cited_data.get('results', [])
                    
                    for work in results:
                        # Проверяем год публикации цитирующей статьи
                        publication_year = work.get('publication_year')
                        
                        # Если год цитирования соответствует целевому году
                        if publication_year == target_citation_year:
                            # Extract DOI from citing work
                            citing_doi = None
                            if work.get('doi'):
                                citing_doi = work['doi']
                                if citing_doi.startswith('https://doi.org/'):
                                    citing_doi = citing_doi[16:]
                            elif work.get('ids', {}).get('doi'):
                                citing_doi = work['ids']['doi']
                                if citing_doi.startswith('https://doi.org/'):
                                    citing_doi = citing_doi[16:]
                            
                            if citing_doi:
                                citing_articles.append({
                                    'doi': citing_doi,
                                    'year': publication_year
                                })
                    
                    if status_text:
                        status_text.text(f"    Page {page}: found {len(results)} citing articles, {len([a for a in citing_articles if a['year'] == target_citation_year])} for target year {target_citation_year}")
                    
                    # Update progress
                    if progress_bar and cited_by_count > 0:
                        progress = min(page * per_page / cited_by_count, 1.0)
                        progress_bar.progress(progress)
                    
                    # Check for next page
                    cited_by_url = cited_data.get('meta', {}).get('next_page')
                    if cited_by_url:
                        page += 1
                        time.sleep(0.3)  # Be polite to API
                    else:
                        break
                else:
                    st.warning(f"    Error fetching citations page {page}: {response_cited.status_code}")
                    break
            except Exception as e:
                st.warning(f"    Error in pagination for {doi}: {e}")
                break

    if status_text:
        status_text.text(f"    Total citing articles for year {target_citation_year}: {len([a for a in citing_articles if a['year'] == target_citation_year])}")
    return citing_articles

def extract_author_names(authors_list):
    """Extract author names in 'Surname FirstInitial' format from Crossref"""
    author_names = []
    for author in authors_list:
        if author.get('family'):
            surname = author['family']
            given = author.get('given', '')
            first_initial = given[0] if given else ''
            author_names.append(f"{surname} {first_initial}.".strip())
    return author_names

def extract_author_names_openalex(authorships):
    """Extract author names from OpenAlex format"""
    author_names = []
    for authorship in authorships:
        author = authorship.get('author', {})
        if author and author.get('display_name'):
            name_parts = author['display_name'].split()
            if len(name_parts) >= 2:
                surname = name_parts[-1]
                first_initial = name_parts[0][0] if name_parts[0] else ''
                author_names.append(f"{surname} {first_initial}.")
            else:
                author_names.append(author['display_name'])
    return author_names

def extract_institutions_crossref(authors_list):
    """Extract UNIQUE institutions from Crossref authors with affiliation"""
    institutions = []
    for author in authors_list:
        if author.get('affiliation'):
            for affiliation in author['affiliation']:
                if affiliation.get('name'):
                    institutions.append(affiliation['name'])
    return list(set(institutions))  # Return unique institutions

def extract_institutions_openalex(authorships):
    """Extract UNIQUE institutions from OpenAlex authorships"""
    institutions = []
    countries = []
    for authorship in authorships:
        for institution in authorship.get('institutions', []):
            if institution.get('display_name'):
                institutions.append(institution['display_name'])
            # Extract country information
            if institution.get('country_code'):
                countries.append(institution['country_code'])
            elif institution.get('country'):
                countries.append(institution['country'])
    return list(set(institutions)), list(set(countries))  # Return unique institutions and countries

def analyze_references(doi):
    """Analyze references for a given DOI"""
    if doi == 'N/A':
        return 0, 0, 0
    
    refs_with_doi = 0
    refs_without_doi = 0
    total_refs = 0

    try:
        url = f"{CROSSREF_BASE_URL}/{doi}"
        resp = requests.get(url)
        if resp.status_code == 200:
            data = resp.json()
            references = data['message'].get('reference', [])
            total_refs = len(references)
            for ref in references:
                if ref.get('DOI'):
                    refs_with_doi += 1
                else:
                    refs_without_doi += 1
    except:
        # Try OpenAlex as fallback
        work_data = get_openalex_work_by_doi(doi)
        if work_data:
            references = work_data.get('referenced_works', [])
            total_refs = len(references)
            refs_with_doi = total_refs  # In OpenAlex, referenced works typically have IDs
            refs_without_doi = 0

    return total_refs, refs_with_doi, refs_without_doi

def get_citation_analysis_enhanced(doi, target_issn, target_journal_name=None, progress_bar=None, status_text=None):
    """Enhanced citation analysis using OpenAlex citing articles - ANALYZES ALL CITATIONS"""
    citing_authors = []
    citing_journals = []
    citing_institutions = []
    citing_countries = []
    self_citation_count = 0
    
    citing_dois = get_citing_articles_openalex(doi, progress_bar, status_text)

    if not citing_dois:
        return citing_authors, citing_journals, citing_institutions, citing_countries, self_citation_count

    if status_text:
        status_text.text(f"    Analyzing ALL {len(citing_dois)} citing articles...")

    # Analyze ALL citing articles - NO LIMITS
    for i, citing_doi in enumerate(citing_dois):
        try:
            # Get citing article details from OpenAlex
            work_data = get_openalex_work_by_doi(citing_doi)
            if work_data:
                # Citing journal - FIXED: Extract proper journal/venue information
                source = work_data.get('primary_location', {}).get('source', {})
                host_venue = work_data.get('host_venue', {})
                
                journal_name = None
                # Try multiple sources for journal name
                if source and source.get('display_name'):
                    journal_name = source['display_name']
                elif host_venue and host_venue.get('display_name'):
                    journal_name = host_venue['display_name']
                elif work_data.get('primary_location', {}).get('source', {}).get('display_name'):
                    journal_name = work_data['primary_location']['source']['display_name']
                
                if journal_name:
                    citing_journals.append(journal_name)
                    
                    # IMPROVED SELF-CITATION DETECTION
                    # Check for self-citation by ISSN or journal name similarity
                    is_self_citation = False
                    
                    # Method 1: Check by ISSN in host_venue
                    if host_venue and host_venue.get('issn'):
                        venue_issns = host_venue['issn']
                        if isinstance(venue_issns, str):
                            venue_issns = [venue_issns]
                        if target_issn in venue_issns:
                            is_self_citation = True
                    
                    # Method 2: Check by journal name similarity (fallback)
                    if not is_self_citation and target_journal_name and target_journal_name.lower() in journal_name.lower():
                        is_self_citation = True
                    
                    if is_self_citation:
                        self_citation_count += 1
                        if status_text:
                            status_text.text(f"    Self-citation detected: {journal_name}")
                
                # Citing authors and institutions
                authorships = work_data.get('authorships', [])
                for authorship in authorships:
                    author = authorship.get('author', {})
                    if author and author.get('display_name'):
                        name_parts = author['display_name'].split()
                        if len(name_parts) >= 2:
                            surname = name_parts[-1]
                            first_initial = name_parts[0][0] if name_parts[0] else ''
                            citing_authors.append(f"{surname} {first_initial}.")
                    
                    # Institutions and countries - COUNT UNIQUE per article
                    article_institutions = set()
                    article_countries = set()
                    for institution in authorship.get('institutions', []):
                        if institution.get('display_name'):
                            article_institutions.add(institution['display_name'])
                        # FIXED: Extract country information properly
                        if institution.get('country_code'):
                            article_countries.add(institution['country_code'])
                        elif institution.get('country'):
                            article_countries.add(institution['country'])
                    
                    citing_institutions.extend(list(article_institutions))
                    citing_countries.extend(list(article_countries))
                
                # Progress update for large citation sets
                if status_text and (i + 1) % 50 == 0:
                    status_text.text(f"   ↳ Processed {i + 1}/{len(citing_dois)} citing articles...")
                
                time.sleep(0.1)  # Be polite to API
                
        except Exception as e:
            st.warning(f"    Error analyzing citing article {citing_doi}: {e}")
            continue

    if status_text:
        status_text.text(f"    Completed analysis of {len(citing_dois)} citing articles")
        status_text.text(f"    Self-citations found: {self_citation_count}")
    return citing_authors, citing_journals, citing_institutions, citing_countries, self_citation_count

def calculate_journal_impact_factor(issn, citation_year, publication_years, status_text, progress_bar):
    """Расчет импакт-фактора журнала как часть общего анализа"""
    
    status_text.text(f" Calculating Impact Factor for {citation_year}...")
    
    # Создаем даты для запроса к Crossref
    from_date = f"{min(publication_years)}-01-01"
    until_date = f"{max(publication_years)}-12-31"
    
    # Получаем статьи за период публикации
    status_text.text(f" Fetching articles from {min(publication_years)} to {max(publication_years)} for Impact Factor calculation...")
    articles = fetch_crossref_articles(issn, from_date, until_date)
    
    if not articles:
        status_text.text(" No articles found for Impact Factor calculation period")
        return None, None, None
    
    # Фильтруем статьи по годам публикации
    publication_articles = []
    for article in articles:
        date_parts = article.get('published', {}).get('date-parts', [])
        if date_parts and date_parts[0]:
            pub_year = date_parts[0][0]
            if pub_year in publication_years:
                publication_articles.append(article)
    
    status_text.text(f" Found {len(publication_articles)} articles published in {publication_years[0]} and {publication_years[1]}")
    
    # Собираем DOI статей за период публикации
    publication_dois = []
    for article in publication_articles:
        doi = article.get('DOI')
        if doi:
            publication_dois.append(doi)
    
    # Подсчитываем цитирования за целевой год
    total_citations = 0
    citation_details = []
    
    if_progress_bar = st.progress(0)
    if_status_text = st.empty()
    
    for i, doi in enumerate(publication_dois):
        if_status_text.text(f" Impact Factor: Analyzing citations for article {i+1}/{len(publication_dois)}...")
        
        citing_articles = get_citing_articles_openalex_with_years(doi, citation_year, if_progress_bar, if_status_text)
        
        # Считаем только цитирования за целевой год
        citations_for_article = len([a for a in citing_articles if a['year'] == citation_year])
        total_citations += citations_for_article
        
        citation_details.append({
            'DOI': doi,
            'Citations': citations_for_article
        })
        
        # Обновляем прогресс
        progress = (i + 1) / len(publication_dois)
        if_progress_bar.progress(progress)
        
        time.sleep(0.2)  # Быть вежливым к API
    
    if_progress_bar.empty()
    if_status_text.empty()
    
    # Рассчитываем импакт-фактор
    if len(publication_articles) > 0:
        impact_factor = total_citations / len(publication_articles)
    else:
        impact_factor = 0
    
    status_text.text(f" Impact Factor {citation_year} calculated: {impact_factor:.4f}")
    
    return impact_factor, total_citations, len(publication_articles)

def main():
    st.title(" Enhanced Journal Quality Analysis Tool")
    st.markdown("""
    ### COMPLETE DATA VERSION
    -  **All articles analyzed**
    -  **All citations counted**
    -  **No limits on citation analysis**
    -  **Complete statistical accuracy**
    -  **Impact Factor Calculation**
    -  ©Chimica Techno Acta, https://chimicatechnoacta.ru / ©developed by daM
    """)

    # Sidebar for input
    with st.sidebar:
        st.header(" Analysis Parameters")
        issn = st.text_input("ISSN", value="XXXX-YYYY", placeholder="e.g., 1234-5678")
        period = st.text_input("Period", value="2023-2025", placeholder="e.g., 2020-2023 or 2020,2021,2022")
        
        st.markdown("---")
        st.info("""
        **Instructions:**
        1. Enter the journal ISSN
        2. Specify the period (year range or individual years)
        3. Click 'Start Analysis' button
        4. Wait for comprehensive results including Impact Factor
        """)

    # Main analysis
    if st.button(" Start Comprehensive Analysis", type="primary"):
        if not issn:
            st.error("Please enter an ISSN")
            return
        
        # Initialize session state for results
        if 'analysis_results' not in st.session_state:
            st.session_state.analysis_results = {}
        
        with st.spinner(" Starting comprehensive journal analysis..."):
            get_articles_analysis(issn, period)

def get_articles_analysis(issn, period):
    """Main analysis function adapted for Streamlit"""
    
    # Parse period
    if '-' in period:
        years = period.split('-')
        from_year = years[0].strip()
        to_year = years[1].strip()
        from_date = f"{from_year}-01-01"
        until_date = f"{to_year}-12-31"
        years_range = list(range(int(from_year), int(to_year) + 1))
    elif ',' in period:
        years = [y.strip() for y in period.split(',')]
        from_year = min(years)
        to_year = max(years)
        from_date = f"{from_year}-01-01"
        until_date = f"{to_year}-12-31"
        years_range = [int(y) for y in years]
    else:
        from_date = f"{period.strip()}-01-01"
        until_date = f"{period.strip()}-12-31"
        from_year = period.strip()
        to_year = period.strip()
        years_range = [int(period.strip())]

    # Progress tracking
    progress_bar = st.progress(0)
    status_text = st.empty()

    # Расчет импакт-фактора в начале анализа
    status_text.text(" Determining Impact Factor calculation parameters...")
    citation_year, publication_years = calculate_impact_factor_years()
    
    impact_factor_data = None
    # Вычисляем импакт-фактор только если период анализа включает нужные годы
    if any(year in years_range for year in publication_years + [citation_year]):
        impact_factor, total_citations, citable_items = calculate_journal_impact_factor(
            issn, citation_year, publication_years, status_text, progress_bar
        )
        if impact_factor is not None:
            impact_factor_data = {
                'year': citation_year,
                'value': impact_factor,
                'citations': total_citations,
                'items': citable_items,
                'publication_years': publication_years
            }
            st.session_state.impact_factor = impact_factor_data

    # Fetch data from Crossref
    status_text.text(" Fetching data from Crossref...")
    crossref_items = fetch_crossref_articles(issn, from_date, until_date)

    if len(crossref_items) == 0:
        st.error(" No articles found for the given ISSN and period.")
        return

    status_text.text(f" Found {len(crossref_items)} articles in Crossref")

    # Try to get target journal name from first article
    target_journal_name = None
    if crossref_items and crossref_items[0].get('container-title'):
        container_title = crossref_items[0].get('container-title')
        if container_title:
            if isinstance(container_title, list):
                target_journal_name = container_title[0]
            else:
                target_journal_name = container_title
            st.info(f" Target journal: {target_journal_name}")

    # Extract DOI list from Crossref results
    dois = []
    for item in crossref_items:
        doi = item.get('DOI')
        if doi:
            dois.append(doi)

    status_text.text(f" Extracted {len(dois)} unique DOIs for analysis")
    progress_bar.progress(0.1)

    # Process data
    all_authors = []
    all_institutions = []
    all_countries = []
    self_citations_by_year = {year: {'total_citations': 0, 'self_citations': 0} for year in years_range}
    reference_stats = []
    all_citing_authors = []
    all_citing_journals = []
    all_citing_institutions = []
    all_citing_countries = []

    # Process authors and institutions from Crossref
    status_text.text(" Processing author and institution data from Crossref...")

    articles_with_institutions = 0
    total_institutions_count = 0

    for i, item in enumerate(crossref_items):
        # Authors
        authors = item.get('author', [])
        author_names = extract_author_names(authors)
        all_authors.extend(author_names)
        
        # Institutions - COUNT UNIQUE PER ARTICLE
        article_institutions = extract_institutions_crossref(authors)
        if article_institutions:
            articles_with_institutions += 1
            total_institutions_count += len(article_institutions)
            all_institutions.extend(article_institutions)

    progress_bar.progress(0.3)

    # Enhanced analysis for ALL articles
    status_text.text(f" Starting enhanced OpenAlex analysis for ALL {len(dois)} articles...")

    openalex_institutions_count = 0
    openalex_countries_count = 0

    for i, doi in enumerate(dois):
        status_text.text(f" Analyzing article {i+1}/{len(dois)}: {doi[:50]}...")
        
        # Get OpenAlex data for this DOI
        work_data = get_openalex_work_by_doi(doi)
        
        if work_data:
            # Extract institutions and countries from OpenAlex
            authorships = work_data.get('authorships', [])
            article_institutions_openalex, article_countries_openalex = extract_institutions_openalex(authorships)
            if article_institutions_openalex:
                openalex_institutions_count += len(article_institutions_openalex)
                all_institutions.extend(article_institutions_openalex)
            if article_countries_openalex:
                openalex_countries_count += len(article_countries_openalex)
                all_countries.extend(article_countries_openalex)
            
            # Get publication year
            publication_year = work_data.get('publication_year')
            if not publication_year:
                for item in crossref_items:
                    if item.get('DOI') == doi:
                        date_parts = item.get('published', {}).get('date-parts', [])
                        if date_parts and date_parts[0]:
                            publication_year = date_parts[0][0]
                        break
            
            # Enhanced citation analysis
            if publication_year and publication_year in years_range:
                article_progress = st.empty()
                citing_authors, citing_journals, citing_institutions, citing_countries, self_citations = get_citation_analysis_enhanced(
                    doi, issn, target_journal_name, progress_bar, article_progress
                )
                
                total_citations_for_article = len(citing_journals)
                self_citations_by_year[publication_year]['total_citations'] += total_citations_for_article
                self_citations_by_year[publication_year]['self_citations'] += self_citations
                
                all_citing_authors.extend(citing_authors)
                all_citing_journals.extend(citing_journals)
                all_citing_institutions.extend(citing_institutions)
                all_citing_countries.extend(citing_countries)
                article_progress.empty()
        
        # Update overall progress
        progress = 0.3 + (i / len(dois)) * 0.4
        progress_bar.progress(progress)
        time.sleep(0.5)

    # Reference analysis
    status_text.text(" Analyzing references...")
    for i, doi in enumerate(dois):
        total_refs, refs_with_doi, refs_without_doi = analyze_references(doi)
        reference_stats.append({
            'DOI': doi,
            'Total References': total_refs,
            'References with DOI': refs_with_doi,
            'References without DOI': refs_without_doi
        })

    progress_bar.progress(0.9)

    # Create analysis reports
    status_text.text(" Generating analysis reports...")

    # 1. Author Frequency
    author_freq = Counter(all_authors)
    author_freq_df = pd.DataFrame(author_freq.most_common(50), columns=['Author', 'Frequency'])

    # 2. Institution Frequency
    institution_freq = Counter(all_institutions)
    institution_freq_df = pd.DataFrame(institution_freq.most_common(50), columns=['Institution', 'Frequency'])

    # 3. Self-citation analysis
    self_citation_data = []
    total_self_citations = 0
    total_all_citations = 0

    for year, stats in self_citations_by_year.items():
        total_citations = stats['total_citations']
        self_citations = stats['self_citations']
        
        if total_citations > 0:
            self_citation_rate = (self_citations / total_citations) * 100
        else:
            self_citation_rate = 0
            
        self_citation_data.append({
            'Year': year,
            'Total Citations': total_citations,
            'Self Citations': self_citations,
            'Self Citation Rate (%)': round(self_citation_rate, 2)
        })
        
        total_self_citations += self_citations
        total_all_citations += total_citations

    self_citation_df = pd.DataFrame(self_citation_data)

    # 4. Reference analysis summary
    if reference_stats:
        ref_df = pd.DataFrame(reference_stats)
        total_refs_sum = ref_df['Total References'].sum()
        if total_refs_sum > 0:
            with_doi_pct = (ref_df['References with DOI'].sum() / total_refs_sum) * 100
            without_doi_pct = (ref_df['References without DOI'].sum() / total_refs_sum) * 100
        else:
            with_doi_pct = 0
            without_doi_pct = 0
            
        reference_analysis_df = pd.DataFrame({
            'Metric': ['Articles Analyzed', 'Total References', 'Average References per Article', 
                      'References with DOI (%)', 'References without DOI (%)'],
            'Value': [
                len(ref_df),
                total_refs_sum,
                round(ref_df['Total References'].mean(), 2) if len(ref_df) > 0 else 0,
                round(with_doi_pct, 2),
                round(without_doi_pct, 2)
            ]
        })
    else:
        reference_analysis_df = pd.DataFrame({'Metric': ['No data available'], 'Value': [0]})

    # 5. Enhanced citation analysis
    citing_author_freq = Counter(all_citing_authors).most_common(20) if all_citing_authors else []
    citing_journal_freq = Counter(all_citing_journals).most_common(20) if all_citing_journals else []
    citing_institution_freq = Counter(all_citing_institutions).most_common(20) if all_citing_institutions else []
    citing_country_freq = Counter(all_citing_countries).most_common(20) if all_citing_countries else []

    max_len = max(
        len(citing_author_freq) if citing_author_freq else 0, 
        len(citing_journal_freq) if citing_journal_freq else 0, 
        len(citing_institution_freq) if citing_institution_freq else 0, 
        len(citing_country_freq) if citing_country_freq else 0,
        1
    )

    citing_authors_padded = [f"{author} ({count})" for author, count in citing_author_freq] + [''] * (max_len - len(citing_author_freq))
    citing_journals_padded = [f"{journal} ({count})" for journal, count in citing_journal_freq] + [''] * (max_len - len(citing_journal_freq))
    citing_institutions_padded = [f"{inst} ({count})" for inst, count in citing_institution_freq] + [''] * (max_len - len(citing_institution_freq))
    citing_countries_padded = [f"{country} ({count})" for country, count in citing_country_freq] + [''] * (max_len - len(citing_country_freq))

    citation_analysis_df = pd.DataFrame({
        'Top Citing Authors': citing_authors_padded,
        'Top Citing Journals': citing_journals_padded,
        'Top Citing Institutions': citing_institutions_padded,
        'Top Citing Countries': citing_countries_padded
    })

    progress_bar.progress(1.0)
    status_text.empty()

    # Display results
    display_results(
        author_freq_df, institution_freq_df, self_citation_df, 
        reference_analysis_df, citation_analysis_df, all_countries,
        crossref_items, articles_with_institutions, total_institutions_count,
        author_freq, institution_freq, all_citing_authors, all_citing_journals,
        all_citing_institutions, all_citing_countries, total_self_citations, total_all_citations,
        impact_factor_data
    )

def display_results(author_freq_df, institution_freq_df, self_citation_df, 
                   reference_analysis_df, citation_analysis_df, all_countries,
                   crossref_items, articles_with_institutions, total_institutions_count,
                   author_freq, institution_freq, all_citing_authors, all_citing_journals,
                   all_citing_institutions, all_citing_countries, total_self_citations, total_all_citations,
                   impact_factor_data=None):
    """Display comprehensive results in Streamlit"""
    
    st.success(" Analysis completed successfully!")
    
    # Показываем импакт-фактор если он был рассчитан
    if impact_factor_data:
        st.header(" Journal Impact Factor")
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Impact Factor Year", impact_factor_data['year'])
        with col2:
            st.metric("Publication Years", f"{impact_factor_data['publication_years'][0]}-{impact_factor_data['publication_years'][1]}")
        with col3:
            st.metric("Citable Items", impact_factor_data['items'])
        with col4:
            st.metric("Total Citations", impact_factor_data['citations'])
        
        st.success(f"## Impact Factor {impact_factor_data['year']}: {impact_factor_data['value']:.4f}")

    # 1. Author Frequency
    st.header(" Author Frequency Analysis")
    col1, col2 = st.columns([2, 1])

    with col1:
        st.dataframe(author_freq_df.head(20), use_container_width=True)

    with col2:
        st.metric("Total Authors", len(author_freq))
        st.metric("Articles Analyzed", len(crossref_items))
        st.metric("Author Mentions", len(author_freq))

    # 2. Institution Frequency
    st.header(" Institution Frequency Analysis")
    col1, col2 = st.columns([2, 1])

    with col1:
        st.dataframe(institution_freq_df.head(20), use_container_width=True)

    with col2:
        st.metric("Total Institutions", len(institution_freq))
        st.metric("Articles with Institution Data", articles_with_institutions)
        st.metric("Avg Institutions per Article", 
                 f"{total_institutions_count/len(crossref_items):.1f}" if len(crossref_items) > 0 else "N/A")

    # 3. Country Analysis
    if all_countries:
        country_freq = Counter(all_countries)
        country_df = pd.DataFrame(country_freq.most_common(20), columns=['Country', 'Frequency'])
        st.header(" Country Distribution Analysis")
        st.dataframe(country_df.head(20), use_container_width=True)

    # 4. Self-citation Analysis
    st.header(" Self-Citation Analysis")
    if not self_citation_df.empty and self_citation_df['Total Citations'].sum() > 0:
        col1, col2 = st.columns([1, 1])
        
        with col1:
            st.dataframe(self_citation_df, use_container_width=True)
        
        with col2:
            st.metric("Total Citations", total_all_citations)
            st.metric("Self-Citations", total_self_citations)
            if total_all_citations > 0:
                self_citation_rate = (total_self_citations / total_all_citations) * 100
                st.metric("Overall Self-Citation Rate", f"{self_citation_rate:.2f}%")
        
        # Plot self-citation trend
        if len(self_citation_df) > 1:
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 5))
            
            # Bar chart
            ax1.bar(self_citation_df['Year'].astype(str), self_citation_df['Self Citation Rate (%)'])
            ax1.set_title('Self-Citation Rate by Year')
            ax1.set_xlabel('Year')
            ax1.set_ylabel('Self-Citation Rate (%)')
            ax1.tick_params(axis='x', rotation=45)
            
            # Line chart
            ax2.plot(self_citation_df['Year'].astype(str), self_citation_df['Self Citation Rate (%)'], 
                    marker='o', linewidth=2, markersize=6, color='red')
            ax2.set_title('Self-Citation Trend')
            ax2.set_xlabel('Year')
            ax2.set_ylabel('Self-Citation Rate (%)')
            ax2.tick_params(axis='x', rotation=45)
            ax2.grid(True, alpha=0.3)
            
            plt.tight_layout()
            st.pyplot(fig)
    else:
        st.info("No sufficient self-citation data available")

    # 5. Reference Analysis
    st.header(" Reference Quality Analysis")
    st.dataframe(reference_analysis_df, use_container_width=True)

    # 6. Citation Network Analysis
    st.header(" Citation Network Analysis")
    if not citation_analysis_df.empty and citation_analysis_df.iloc[0, 0] != '':
        st.dataframe(citation_analysis_df, use_container_width=True)
        
        # Citation metrics
        total_citing_authors = len(all_citing_authors)
        total_citing_journals = len(set(all_citing_journals))
        total_citing_institutions = len(set(all_citing_institutions))
        total_citing_countries = len(set(all_citing_countries))
        
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("Citing Authors", total_citing_authors)
        with col2:
            st.metric("Citing Journals", total_citing_journals)
        with col3:
            st.metric("Citing Institutions", total_citing_institutions)
        with col4:
            st.metric("Citing Countries", total_citing_countries)
        with col5:
            st.metric("Total Citations", len(all_citing_journals))
        
        # Visualization
        if total_citing_journals > 0:
            fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(18, 6))
            
            # Top Citing Journals
            citing_journal_counts = Counter(all_citing_journals).most_common(10)
            if citing_journal_counts:
                journals, counts = zip(*citing_journal_counts)
                ax1.bar(range(len(journals)), counts)
                ax1.set_title('Top 10 Citing Journals')
                ax1.set_xlabel('Journals')
                ax1.set_ylabel('Citation Count')
                ax1.set_xticks(range(len(journals)))
                ax1.set_xticklabels([j[:20] + '...' for j in journals], rotation=45)
            
            # Citation Distribution by Country
            citing_country_counts = Counter(all_citing_countries).most_common(10)
            if citing_country_counts:
                countries, country_counts = zip(*citing_country_counts)
                ax2.pie(country_counts, labels=countries, autopct='%1.1f%%')
                ax2.set_title('Citation Distribution by Country')
            else:
                ax2.text(0.5, 0.5, 'No country data', ha='center', va='center')
                ax2.set_title('Citation Distribution by Country')
            
            # Top Citing Authors
            author_citation_counts = Counter(all_citing_authors).most_common(10)
            if author_citation_counts:
                authors, author_counts = zip(*author_citation_counts)
                ax3.bar(range(len(authors)), author_counts, color='green')
                ax3.set_title('Top 10 Citing Authors')
                ax3.set_xlabel('Authors')
                ax3.set_ylabel('Citation Count')
                ax3.set_xticks(range(len(authors)))
                ax3.set_xticklabels([a[:15] + '...' for a in authors], rotation=45)
            else:
                ax3.text(0.5, 0.5, 'No author data', ha='center', va='center')
                ax3.set_title('Top 10 Citing Authors')
            
            plt.tight_layout()
            st.pyplot(fig)
    else:
        st.info("No citation analysis data available")

    # Download section
    st.header(" Download Analysis Results")

    datasets = {
        'author_frequency.csv': author_freq_df,
        'institution_frequency.csv': institution_freq_df,
        'self_citation_analysis.csv': self_citation_df,
        'reference_analysis.csv': reference_analysis_df,
        'citation_analysis.csv': citation_analysis_df
    }

    for filename, dataframe in datasets.items():
        if not dataframe.empty and len(dataframe) > 0:
            csv = dataframe.to_csv(index=False, encoding='utf-8')
            st.download_button(
                label=f" Download {filename}",
                data=csv,
                file_name=filename,
                mime="text/csv",
                key=filename
            )

if __name__ == "__main__":
    main()

