# overseas_companies_analysis.py
# Analyze sampled Companies House data for director origins and compliance indicators

import json
import math
from datetime import datetime

# Constants
INPUT_FILE = "overseas_directors_sample.json"
UK_VARIANT_FILE = "overseas_companies_UK_variants.txt"
Z95 = 1.96  # for 95% significance


def load_UK_variants():
    # it's a conservative list, including items where it's not clear the director is actually UK (e.g. "Property Consultant")
    # Read variants from a file, one per line
    with open(UK_VARIANT_FILE, encoding="utf-8") as f:
        # strip whitespace and skip empty lines
        variations_on_uk = [line.strip() for line in f if line.strip()]

    # Build a case-folded set
    return {variant.casefold() for variant in variations_on_uk}

def inspect_countries(sampled, uk_variants):
    # Display countries for inspection
    countries = extract_director_countries(sampled)
    print(f"\nFound {len(countries)} unique director countries, excluding those I identify as UK:")
    for c in sorted(countries):
        if c.strip().casefold() not in uk_variants:
            print(f"{c}")
    print("\nIf any UK variants appear above, update UK_COUNTRY_VARIANTS and rerun. Failure to do this will mean the results will be unreliable.")


def load_sampled_companies(input_file):
    """
    Load the sampled companies JSON into a dictionary.
    """
    with open(input_file, 'r') as f:
        data = json.load(f)
    return data.get('sampled_companies', {})


def extract_director_countries(sampled_companies):
    """
    Collect unique country strings from all directors in the sample.
    This is to make sure the user has correctly added all UK variants in the sample to the variants text file
    """
    countries = set()
    for info in sampled_companies.values():
        for officer in info.get('directors', []):
            
            country = officer.get('country_of_residence') or officer.get('residence_country')
            address_country = officer.get('address', {}).get('country')
            
            # where they say they're resident
            if country:
                countries.add(country.strip())
            
            # where they give an address
            if address_country:
                countries.add(address_country.strip())
            
    return countries


def count_companies_by_uk_director_status(sampled_companies, uk_variants):
    """
    Return dicts for total counts and classification of companies by UK director presence.
    """
    counts = {'with_uk': 0, 'without_uk': 0, 'questionable_residence': 0, 'total_directors': 0}
        
    for info in sampled_companies.values():
        has_uk = False
        
        for officer in info.get('directors', []):
            
            counts['total_directors'] += 1
            
            country = officer.get('country_of_residence') or officer.get('residence_country')       
            address_country = officer.get('address', {}).get('country')
                
            # if any director is in the UK then we mark this company as having a UK director   
            if country and country.strip().casefold() in uk_variants:
                
                # provided their stated address is also the UK. 
                if address_country and address_country.strip().casefold() in uk_variants:
                    has_uk = True

                # Keep track of such suspect cases
                else:
                    counts['questionable_residence'] += 1
                    
        if has_uk:
            counts['with_uk'] += 1
        else:
            counts['without_uk'] += 1
        
            
    counts['total_companies'] = counts['with_uk'] + counts['without_uk']
    return counts

def count_foreign_and_uk_directors(sampled, uk_variants):
    # Basic UK director stats
    counts = count_companies_by_uk_director_status(sampled, uk_variants)
    
    
    with_uk = counts['with_uk']
    without_uk = counts['without_uk']
    total_companies = counts['total_companies']
    pct_foreign = without_uk / total_companies if total_companies else 0
    moe_foreign = Z95 * math.sqrt(pct_foreign * (1 - pct_foreign) / total_companies) if total_companies else 0
    
    questionable_residence = counts['questionable_residence']
    total_directors = counts['total_directors']
    pct_questionable_residence = questionable_residence / total_directors if total_directors else 0
    moe_questionable_residence = Z95 * math.sqrt(pct_questionable_residence * (1 - pct_questionable_residence) / total_directors) if total_directors else 0

    print(f"\nTotal: {total_companies:,}, with UK director: {with_uk:,}, without: {without_uk:,}")
    print(f"Proportion companies all-foreign: {pct_foreign * 100:.1f}% ±{moe_foreign * 100:.2f}%")
    print(f"{total_directors} directors of which {pct_questionable_residence * 100:.1f}% ±{moe_questionable_residence * 100:.2f}% have questionable residence")
    
    return counts


def analyze_compliance(sampled_companies, uk_variants):
    """
    Analyze compliance indicators for companies with/without UK directors.
    Returns a dict with metrics for each group.
    """
    # Initialize structure
    metrics = {
        'with_uk': {'late_confstmt': 0, 'late_accounts': 0, 'default_address': 0},
        'without_uk': {'late_confstmt': 0, 'late_accounts': 0, 'default_address': 0}
    }
    today = datetime.utcnow().date()

    for info in sampled_companies.values():
        # Determine group
        has_uk = False
        for officer in info.get('directors', []):
            country = officer.get('country_of_residence') or officer.get('residence_country')
            address_country = officer.get('address', {}).get('country')            
            
            # mark director as UK if their residence AND address country is UK
            if (country and country.strip().casefold() in uk_variants) and (address_country and address_country.strip().casefold() in uk_variants):
                has_uk = True
                break
        group = 'with_uk' if has_uk else 'without_uk'

        data = info.get('company_data', {})
        # Late confirmation statement?
        conf_due = str(data.get('ConfStmtNextDueDate', '')).strip()
        try:
            conf_date = datetime.strptime(conf_due, '%d/%m/%Y').date()
            if conf_date < today:
                metrics[group]['late_confstmt'] += 1
        except Exception:
            pass
        # Late accounts filing?
        acc_due = str(data.get('Accounts.NextDueDate', '')).strip()
        try:
            acc_date = datetime.strptime(acc_due, '%d/%m/%Y').date()
            if acc_date < today:
                metrics[group]['late_accounts'] += 1
        except Exception:
            pass
        
        # Default office address?
        addr = str(data.get('RegAddress.AddressLine1', '')).strip()
        if 'default address' in addr.lower():
            metrics[group]['default_address'] += 1

        # Check each director's service address if company address not flagged
        else:
            for officer in info.get('directors', []):
                director_address = officer.get('address', {}) or {}
                for val in director_address.values():
                    if isinstance(val, str) and 'default address' in val.lower():
                        metrics[group]['default_address'] += 1
                        break
    return metrics

def display_compliance_indicators(counts, metrics):
    print("\nCompliance indicators by group:")
    for group in ['with_uk', 'without_uk']:
        n = counts[group]
        print(f"\nGroup '{group}' (n={n:,}):")
        # For each compliance metric, show count, percent, and 95% margin of error
        for key, label in [
            ('late_confstmt', 'Late confirmation statement'),
            ('late_accounts', 'Late accounts filing'),
            ('default_address', 'Default office address')
        ]:
            count = metrics[group][key]
            p = count / n if n else 0
            moe_metric = Z95 * math.sqrt(p * (1 - p) / n) if n else 0
            print(f"  {label}: {count:,} ({p*100:.2f}% ±{moe_metric*100:.2f}%)")


def calculate_and_print_default_address_ratio(counts, metrics, Z95):
    """
    Calculates the ratio of default address usage between 'without_uk' and 'with_uk' groups
    and its margin of error, then prints it.
    """
    stats_for_ratio = {}
    # Calculate proportions and their margins of error for default_address
    for group in ['with_uk', 'without_uk']:
        n = counts[group]
        count = metrics[group]['default_address']
        
        p = 0.0
        if n > 0:
            p = count / n
        
        moe_p = 0.0
        if n > 0 and p > 0 and p < 1: # Standard formula for MOE of a proportion
            moe_p = Z95 * math.sqrt(p * (1 - p) / n)
        elif n > 0 and (p == 0 or p == 1): # If p is 0 or 1, MOE is technically 0 by Wald interval for large n.
                                        # For small n, other CI methods might be preferred but we stick to script's method.
            moe_p = Z95 * math.sqrt(p * (1 - p) / n) # This will evaluate to 0

        stats_for_ratio[group] = {'p': p, 'moe_p': moe_p, 'n': n, 'count': count}

    p_uk = stats_for_ratio['with_uk']['p']
    moe_p_uk = stats_for_ratio['with_uk']['moe_p']
    p_foreign = stats_for_ratio['without_uk']['p']
    moe_p_foreign = stats_for_ratio['without_uk']['moe_p']

    ratio = p_foreign / p_uk

    # Calculate margin of error for the ratio R = P_foreign / P_uk
    # (MOE_R / R)^2 = (MOE_P_foreign / P_foreign)^2 + (MOE_P_uk / P_uk)^2
    # MOE_R = R * sqrt((MOE_P_foreign / P_foreign)^2 + (MOE_P_uk / P_uk)^2)
    
    # Handle cases where proportions might be zero for relative error calculation
    rel_err_sq_foreign = 0.0
    if p_foreign > 0 and moe_p_foreign > 0: # moe_p can be 0 if p is 0 or 1
        rel_err_sq_foreign = (moe_p_foreign / p_foreign)**2
    
    rel_err_sq_uk = 0.0
    if p_uk > 0 and moe_p_uk > 0: # moe_p_uk can be 0 if p_uk is 0 or 1
        rel_err_sq_uk = (moe_p_uk / p_uk)**2
    
    # If a proportion is 0 (and its MOE is 0), its term in the sum of relative errors squared is 0.
    # If a proportion is 1 (and its MOE is 0), its term is also 0.
    # If a MOE is 0 because p=0 or p=1 (perfect certainty for the sample), 
    # it implies no uncertainty from that term for the ratio's error.

    moe_ratio = 0.0
    if ratio != 0 : # If ratio is 0 (because p_foreign is 0), then moe_ratio is 0
        # (assuming moe_p_foreign is also 0 when p_foreign is 0)
        if rel_err_sq_foreign > 0 or rel_err_sq_uk > 0:
             moe_ratio = abs(ratio) * math.sqrt(rel_err_sq_foreign + rel_err_sq_uk)
        # If both rel_err_sq are 0 (e.g. both p are 1.0 with 0 MOE), moe_ratio is 0.


    print(f"\nRatio of fraud in foreign vs UK companies: {ratio:.2f} ±{moe_ratio:.2f}")
    

def main():
    
    
    uk_variants = load_UK_variants()
    sampled = load_sampled_companies(INPUT_FILE)
    
    
    print(f"\nLoaded {len(sampled)} sampled companies.")
    
    inspect_countries(sampled, uk_variants)

    counts = count_foreign_and_uk_directors(sampled, uk_variants)
    metrics = analyze_compliance(sampled, uk_variants)    
    display_compliance_indicators(counts, metrics)
    calculate_and_print_default_address_ratio(counts, metrics, Z95)

if __name__ == '__main__':
    main()
