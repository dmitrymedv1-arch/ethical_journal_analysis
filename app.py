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
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# API endpoints
CROSSREF_BASE_URL = "https://api.crossref.org/works"
OPENALEX_BASE_URL = "https://api.openalex.org/works"

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
            
            status_text.text(f"📥 Retrieved {len(items)} articles...")
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
    
    work_data = get_openalex_work_by_doi(doi)
    if not work_data:
        return citing_dois
    
    cited_by_count = work_data.get('cited_by_count', 0)
    if status_text:
        status_text.text(f"   📊 Article has {cited_by_count} citations")
    
    if cited_by_count > 0:
        page = 1
        per_page = 200
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
                        status_text.text(f"   ✅ Page {page}: found {len(results)} citing articles")
                    
                    if progress_bar and cited_by_count > 0:
                        progress = min(page * per_page / cited_by_count, 1.0)
                        progress_bar.progress(progress)
                    
                    cited_by_url = cited_data.get('meta', {}).get('next_page')
                    if cited_by_url:
                        page += 1
                        time.sleep(0.3)
                    else:
                        break
                else:
                    st.warning(f"   ❌ Error fetching citations page {page}: {response_cited.status_code}")
                    break
            except Exception as e:
                st.warning(f"   ❌ Error in pagination for {doi}: {e}")
                break
    
    if status_text:
        status_text.text(f"   ✅ Total citing articles collected: {len(citing_dois)}")
    return citing_dois

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
    return list(set(institutions))

def extract_institutions_openalex(authorships):
    """Extract UNIQUE institutions from OpenAlex authorships"""
    institutions = []
    countries = []
    for authorship in authorships:
        for institution in authorship.get('institutions', []):
            if institution.get('display_name'):
                institutions.append(institution['display_name'])
            if institution.get('country_code'):
                countries.append(institution['country_code'])
            elif institution.get('country'):
                countries.append(institution['country'])
    return list(set(institutions)), list(set(countries))

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
        work_data = get_openalex_work_by_doi(doi)
        if work_data:
            references = work_data.get('referenced_works', [])
            total_refs = len(references)
            refs_with_doi = total_refs
            refs_without_doi = 0
    
    return total_refs, refs_with_doi, refs_without_doi

def get_citation_analysis_enhanced(doi, target_issn, target_journal_name=None, progress_bar=None, status_text=None, citation_year=None):
    """Enhanced citation analysis using OpenAlex citing articles - ANALYZES ALL CITATIONS"""
    citing_authors = []
    citing_journals = []
    citing_institutions = []
    citing_countries = []
    self_citation_count = 0
    citations_in_target_year = 0
    
    citing_dois = get_citing_articles_openalex(doi, progress_bar, status_text)
    
    if not citing_dois:
        return citing_authors, citing_journals, citing_institutions, citing_countries, self_citation_count, citations_in_target_year
    
    if status_text:
        status_text.text(f"   🔍 Analyzing ALL {len(citing_dois)} citing articles...")
    
    for i, citing_doi in enumerate(citing_dois):
        try:
            work_data = get_openalex_work_by_doi(citing_doi)
            if work_data:
                # Проверяем год цитирования для импакт-фактора
                pub_year = work_data.get('publication_year')
                if pub_year == citation_year:
                    citations_in_target_year += 1
                
                source = work_data.get('primary_location', {}).get('source', {})
                host_venue = work_data.get('host_venue', {})
                
                journal_name = None
                if source and source.get('display_name'):
                    journal_name = source['display_name']
                elif host_venue and host_venue.get('display_name'):
                    journal_name = host_venue['display_name']
                elif work_data.get('primary_location', {}).get('source', {}).get('display_name'):
                    journal_name = work_data['primary_location']['source']['display_name']
                
                if journal_name:
                    citing_journals.append(journal_name)
                    is_self_citation = False
                    
                    if host_venue and host_venue.get('issn'):
                        venue_issns = host_venue['issn']
                        if isinstance(venue_issns, str):
                            venue_issns = [venue_issns]
                        if target_issn in venue_issns:
                            is_self_citation = True
                    
                    if not is_self_citation and target_journal_name and target_journal_name.lower() in journal_name.lower():
                        is_self_citation = True
                    
                    if is_self_citation:
                        self_citation_count += 1
                        if status_text:
                            status_text.text(f"   🔍 Self-citation detected: {journal_name}")
                
                authorships = work_data.get('authorships', [])
                for authorship in authorships:
                    author = authorship.get('author', {})
                    if author and author.get('display_name'):
                        name_parts = author['display_name'].split()
                        if len(name_parts) >= 2:
                            surname = name_parts[-1]
                            first_initial = name_parts[0][0] if name_parts[0] else ''
                            citing_authors.append(f"{surname} {first_initial}.")
                    
                    article_institutions = set()
                    article_countries = set()
                    for institution in authorship.get('institutions', []):
                        if institution.get('display_name'):
                            article_institutions.add(institution['display_name'])
                        if institution.get('country_code'):
                            article_countries.add(institution['country_code'])
                        elif institution.get('country'):
                            article_countries.add(institution['country'])
                    
                    citing_institutions.extend(list(article_institutions))
                    citing_countries.extend(list(article_countries))
                
                if status_text and (i + 1) % 50 == 0:
                    status_text.text(f"   ↳ Processed {i + 1}/{len(citing_dois)} citing articles...")
                
                time.sleep(0.1)
                
        except Exception as e:
            st.warning(f"   ❌ Error analyzing citing article {citing_doi}: {e}")
            continue
    
    if status_text:
        status_text.text(f"   ✅ Completed analysis of {len(citing_dois)} citing articles")
        status_text.text(f"   🔄 Self-citations found: {self_citation_count}")
        if citation_year:
            status_text.text(f"   📊 Citations in {citation_year}: {citations_in_target_year}")
    return citing_authors, citing_journals, citing_institutions, citing_countries, self_citation_count, citations_in_target_year

def main():
    st.title("📊 Enhanced Journal Quality Analysis Tool")
    st.markdown("""
    ### COMPLETE DATA VERSION
    - ✅ **All articles analyzed**
    - ✅ **All citations counted**
    - ✅ **No limits on citation analysis**
    - ✅ **Complete statistical accuracy**
    """)
    
    with st.sidebar:
        st.header("🔍 Analysis Parameters")
        issn = st.text_input("ISSN", value="XXXX-YYYY", placeholder="e.g., 1234-5678")
        period = st.text_input("Period", value="2023-2025", placeholder="e.g., 2020-2023 or 2020,2021,2022")
        
        st.markdown("---")
        st.info("""
        **Instructions:**
        1. Enter the journal ISSN
        2. Specify the period (year range or individual years)
        3. Click 'Start Analysis' button
        4. Wait for comprehensive results
        """)
    
    if st.button("🚀 Start Comprehensive Analysis", type="primary"):
        if not issn:
            st.error("Please enter an ISSN")
            return
        
        if 'analysis_results' not in st.session_state:
            st.session_state.analysis_results = {}
        
        with st.spinner("🚀 Starting comprehensive journal analysis..."):
            get_articles_analysis(issn, period)

def get_articles_analysis(issn, period):
    """Main analysis function adapted for Streamlit with Impact Factor calculation"""
    
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

    progress_bar = st.progress(0)
    status_text = st.empty()

    status_text.text("📥 Fetching data from Crossref...")
    crossref_items = fetch_crossref_articles(issn, from_date, until_date)
    
    if len(crossref_items) == 0:
        st.error("❌ No articles found for the given ISSN and period.")
        return
    
    status_text.text(f"✅ Found {len(crossref_items)} articles in Crossref")
    
    target_journal_name = None
    if crossref_items and crossref_items[0].get('container-title'):
        container_title = crossref_items[0].get('container-title')
        if container_title:
            if isinstance(container_title, list):
                target_journal_name = container_title[0]
            else:
                target_journal_name = container_title
            st.info(f"📖 Target journal: {target_journal_name}")
    
    dois = []
    for item in crossref_items:
        doi = item.get('DOI')
        if doi:
            dois.append(doi)

    status_text.text(f"📋 Extracted {len(dois)} unique DOIs for analysis")
    progress_bar.progress(0.1)

    current_date = datetime(2025, 10, 25)
    citation_year = current_date.year - 1  # 2024 для 2025
    article_years = [citation_year - 1, citation_year - 2]  # 2023 и 2022

    all_authors = []
    all_institutions = []
    all_countries = []
    self_citations_by_year = {year: {'total_citations': 0, 'self_citations': 0, 'citations_in_target_year': 0} for year in years_range}
    reference_stats = []
    all_citing_authors = []
    all_citing_journals = []
    all_citing_institutions = []
    all_citing_countries = []
    
    articles_in_period = []
    for item in crossref_items:
        date_parts = item.get('published', {}).get('date-parts', [])
        if date_parts and date_parts[0]:
            publication_year = date_parts[0][0]
            if publication_year in article_years:
                articles_in_period.append(item)
    
    num_articles_for_if = len([item.get('DOI') for item in articles_in_period if item.get('DOI')])

    status_text.text("👥 Processing author and institution data from Crossref...")
    
    articles_with_institutions = 0
    total_institutions_count = 0
    
    for i, item in enumerate(crossref_items):
        authors = item.get('author', [])
        author_names = extract_author_names(authors)
        all_authors.extend(author_names)
        
        article_institutions = extract_institutions_crossref(authors)
        if article_institutions:
            articles_with_institutions += 1
            total_institutions_count += len(article_institutions)
            all_institutions.extend(article_institutions)
    
    progress_bar.progress(0.3)
    
    status_text.text(f"🔍 Starting enhanced OpenAlex analysis for ALL {len(dois)} articles...")
    
    openalex_institutions_count = 0
    openalex_countries_count = 0
    total_citations_in_target_year = 0
    
    for i, doi in enumerate(dois):
        status_text.text(f"📊 Analyzing article {i+1}/{len(dois)}: {doi[:50]}...")
        
        work_data = get_openalex_work_by_doi(doi)
        
        if work_data:
            authorships = work_data.get('authorships', [])
            article_institutions_openalex, article_countries_openalex = extract_institutions_openalex(authorships)
            if article_institutions_openalex:
                openalex_institutions_count += len(article_institutions_openalex)
                all_institutions.extend(article_institutions_openalex)
            if article_countries_openalex:
                openalex_countries_count += len(article_countries_openalex)
                all_countries.extend(article_countries_openalex)
            
            publication_year = work_data.get('publication_year')
            if not publication_year:
                for item in crossref_items:
                    if item.get('DOI') == doi:
                        date_parts = item.get('published', {}).get('date-parts', [])
                        if date_parts and date_parts[0]:
                            publication_year = date_parts[0][0]
                        break
            
            if publication_year and publication_year in years_range:
                article_progress = st.empty()
                citing_authors, citing_journals, citing_institutions, citing_countries, self_citations, citations_in_target_year = get_citation_analysis_enhanced(
                    doi, issn, target_journal_name, progress_bar, article_progress, citation_year
                )
                
                total_citations_for_article = len(citing_journals)
                self_citations_by_year[publication_year]['total_citations'] += total_citations_for_article
                self_citations_by_year[publication_year]['self_citations'] += self_citations
                self_citations_by_year[publication_year]['citations_in_target_year'] += citations_in_target_year
                
                if publication_year in article_years:
                    total_citations_in_target_year += citations_in_target_year
                
                all_citing_authors.extend(citing_authors)
                all_citing_journals.extend(citing_journals)
                all_citing_institutions.extend(citing_institutions)
                all_citing_countries.extend(citing_countries)
                article_progress.empty()
        
        progress = 0.3 + (i / len(dois)) * 0.4
        progress_bar.progress(progress)
        time.sleep(0.5)
    
    impact_factor = total_citations_in_target_year / num_articles_for_if if num_articles_for_if > 0 else 0.0
    
    status_text.text("📚 Analyzing references...")
    for i, doi in enumerate(dois):
        total_refs, refs_with_doi, refs_without_doi = analyze_references(doi)
        reference_stats.append({
            'DOI': doi,
            'Total References': total_refs,
            'References with DOI': refs_with_doi,
            'References without DOI': refs_without_doi
        })
    
    progress_bar.progress(0.9)
    
    status_text.text("📈 Generating analysis reports...")
    
    author_freq = Counter(all_authors)
    author_freq_df = pd.DataFrame(author_freq.most_common(50), columns=['Author', 'Frequency'])
    
    institution_freq = Counter(all_institutions)
    institution_freq_df = pd.DataFrame(institution_freq.most_common(50), columns=['Institution', 'Frequency'])
    
    self_citation_data = []
    total_self_citations = 0
    total_all_citations = 0
    
    for year, stats in self_citations_by_year.items():
        total_citations = stats['total_citations']
        self_citations = stats['self_citations']
        citations_in_target_year = stats['citations_in_target_year']
        
        if total_citations > 0:
            self_citation_rate = (self_citations / total_citations) * 100
        else:
            self_citation_rate = 0
            
        self_citation_data.append({
            'Year': year,
            'Total Citations': total_citations,
            'Self Citations': self_citations,
            f'Citations in {citation_year}': citations_in_target_year,
            'Self Citation Rate (%)': round(self_citation_rate, 2)
        })
        
        total_self_citations += self_citations
        total_all_citations += total_citations
    
    self_citation_df = pd.DataFrame(self_citation_data)
    
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
    
    display_results(
        author_freq_df, institution_freq_df, self_citation_df, 
        reference_analysis_df, citation_analysis_df, all_countries,
        crossref_items, articles_with_institutions, total_institutions_count,
        author_freq, institution_freq, all_citing_authors, all_citing_journals,
        all_citing_institutions, all_citing_countries, total_self_citations, total_all_citations,
        impact_factor, total_citations_in_target_year, num_articles_for_if, citation_year, article_years
    )

def display_results(author_freq_df, institution_freq_df, self_citation_df, 
                   reference_analysis_df, citation_analysis_df, all_countries,
                   crossref_items, articles_with_institutions, total_institutions_count,
                   author_freq, institution_freq, all_citing_authors, all_citing_journals,
                   all_citing_institutions, all_citing_countries, total_self_citations, total_all_citations,
                   impact_factor, total_citations_in_target_year, num_articles_for_if, citation_year, article_years):
    """Display comprehensive results in Streamlit including Impact Factor"""
    
    st.success("✅ Analysis completed successfully!")
    
    st.header("📊 Impact Factor")
    st.metric(f"Impact Factor ({citation_year})", f"{impact_factor:.2f}")
    st.write(f"Calculated as {total_citations_in_target_year} citations in {citation_year} to {num_articles_for_if} articles published in {article_years[0]}–{article_years[1]}")
    
    st.header("👥 Author Frequency Analysis")
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.dataframe(author_freq_df.head(20), use_container_width=True)
    
    with col2:
        st.metric("Total Authors", len(author_freq))
        st.metric("Articles Analyzed", len(crossref_items))
        st.metric("Author Mentions", len(author_freq))
    
    st.header("🏛️ Institution Frequency Analysis")
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.dataframe(institution_freq_df.head(20), use_container_width=True)
    
    with col2:
        st.metric("Total Institutions", len(institution_freq))
        st.metric("Articles with Institution Data", articles_with_institutions)
        st.metric("Avg Institutions per Article", 
                 f"{total_institutions_count/len(crossref_items):.1f}" if len(crossref_items) > 0 else "N/A")
    
    if all_countries:
        country_freq = Counter(all_countries)
        country_df = pd.DataFrame(country_freq.most_common(20), columns=['Country', 'Frequency'])
        st.header("🌍 Country Distribution Analysis")
        st.dataframe(country_df.head(20), use_container_width=True)
    
    st.header("🔄 Self-Citation Analysis")
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
        
        if len(self_citation_df) > 1:
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 5))
            
            ax1.bar(self_citation_df['Year'].astype(str), self_citation_df['Self Citation Rate (%)'])
            ax1.set_title('Self-Citation Rate by Year')
            ax1.set_xlabel('Year')
            ax1.set_ylabel('Self-Citation Rate (%)')
            ax1.tick_params(axis='x', rotation=45)
            
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
    
    st.header("📚 Reference Quality Analysis")
    st.dataframe(reference_analysis_df, use_container_width=True)
    
    st.header("🔗 Citation Network Analysis")
    if not citation_analysis_df.empty and citation_analysis_df.iloc[0, 0] != '':
        st.dataframe(citation_analysis_df, use_container_width=True)
        
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
        
        if total_citing_journals > 0:
            fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(18, 6))
            
            citing_journal_counts = Counter(all_citing_journals).most_common(10)
            if citing_journal_counts:
                journals, counts = zip(*citing_journal_counts)
                ax1.bar(range(len(journals)), counts)
                ax1.set_title('Top 10 Citing Journals')
                ax1.set_xlabel('Journals')
                ax1.set_ylabel('Citation Count')
                ax1.set_xticks(range(len(journals)))
                ax1.set_xticklabels([j[:20] + '...' for j in journals], rotation=45)
            
            citing_country_counts = Counter(all_citing_countries).most_common(10)
            if citing_country_counts:
                countries, country_counts = zip(*citing_country_counts)
                ax2.pie(country_counts, labels=countries, autopct='%1.1f%%')
                ax2.set_title('Citation Distribution by Country')
            else:
                ax2.text(0.5, 0.5, 'No country data', ha='center', va='center')
                ax2.set_title('Citation Distribution by Country')
            
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
    
    st.header("💾 Download Analysis Results")
    
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
                label=f"📥 Download {filename}",
                data=csv,
                file_name=filename,
                mime="text/csv",
                key=filename
            )

if __name__ == "__main__":
    main()
