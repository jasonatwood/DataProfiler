import pandas as pd
import numpy as np
from pathlib import Path
import logging
import re

class _FileObj:
    def __init__(self, path_obj, dataframe=None, dataframe_name=None, **kwargs):
        """
        Create a FileObj instance that has a single attribute, df which is a pandas dataframe
        supports xls, xlsx, csv, tsv files. Only the first worksheet in an Excel workbook
        with multiple sheets will be read.
        param: use any keyword parameters valid in pandas.read_csv()
        """
        # Initialize logging
        self.log = logging.getLogger()
        self.log.handlers = []
        self.log.setLevel(logging.INFO)
        log_fmt = logging.Formatter('%(levelname)s: %(asctime)s %(thread)d %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        screen = logging.StreamHandler()
        screen.setFormatter(log_fmt)
        self.log.addHandler(screen)
        
        self.df = None
        # df_name must be unique to create unique output filenames
        self.df_name = None
        
        # log.info('Creating FileObj')
        if path_obj == 'dataframe':
            if dataframe is None:
                raise Exception('No dataframe was assigned to the "dataframe=" argument.')
            else:
                self.df = dataframe
                if dataframe_name is None:
                    raise Exception('If profiling a dataframe, argument dataframe_name must be a unique string')
                else:
                    self.df_name = dataframe_name
        elif path_obj.is_file():
            if path_obj.suffix in('.xls', '.xlsx'):
                try:
                    self.df = pd.read_excel(path_obj, **kwargs)
                except Exception as error:
                    self.log.exception(error)

            elif path_obj.suffix in ['.csv', '.tsv', '.txt']:
                try:
                    self.df = pd.read_csv(path_obj, **kwargs)
                except Exception as error:
                    self.log.exception(error)
        else:
            raise Exception(f'{path_obj.name} is not a file.  Please use a valid text or excel file')
            
        if self.df is None:
            self.log.warning(f'{path_obj.name} was not parsed, please check file format and kwargs')
        else:
            # log.info('Created FileObj')
            self.id_cols = []
            self.dim_cols = []
            self.path_obj = path_obj
        
        
    def get_columns(self):
        """
        Not currently used as the column list is contained in the more comprehensive Data Types output 
        returns: dataframe of columns from file
        """
        self.log.info('Retrieving Columns')
        return pd.DataFrame(self.df.columns, columns=['Columns'])
    
    
    def get_data_types(self):
        """
        method that sets values for self.id_cols and self.dim_cols, additionally the 
        returns: dataframe of column names and their data types
        """
        self.log.info('Retrieving Data Types')
                
        df = pd.DataFrame(self.df.dtypes, columns=['Data Type'])
        df.index.name = 'Column Name'
        df = df.reset_index()
        
        # Replace unacceptable characters in column names with undercores
        df['Clean Column Name'] = df['Column Name'].str.replace(r'[\(\[\/,\s\-:\]\)\+]+', '_', regex=True)
        # less than, greater than
        df['Clean Column Name'] = df['Clean Column Name'].str.replace(r'<', '_lt_', regex=True)
        df['Clean Column Name'] = df['Clean Column Name'].str.replace(r'>', '_gt_', regex=True)

        # replace multiple underscores with a single underscore
        df['Clean Column Name'] = df['Clean Column Name'].str.replace(r'_+', '_', regex=True)
        # remove leading and trailing underscores
        df['Clean Column Name'] = df['Clean Column Name'].str.strip('_')

        # insert underscore for column names that might be IDs and use camel case
        df['Clean Column Name'] = df['Clean Column Name'].apply(lambda x: _modify_camel_case_id_names(x))
        
        """results = re.search(r'([A-Z]+[a-z])|([a-z]+[A-Z])', text)
        for group in results.groups():
            if group:
                text.replace(group, group[:-1]+'_'+group[-1])
        """

        # lower case the clean column name
        df['Clean Column Name'] = df['Clean Column Name'].str.lower()

        # replace obscure data type names with clear names
        replace_dict = {'datetime64[ns]': 'date/datetime', 'object':'string'}
        df['Data Type'] = df['Data Type'].replace(to_replace=replace_dict)
            
        # identify ID columns
        id_col_pat = re.compile(r"(?:[-_\s]+id|[-_\s]+ID$)|(?:[a-z]+ID$)|(?:[-_\s]+code)",)
        df['Potential ID Column'] = df['Column Name'].apply(lambda x: True if re.search(id_col_pat, x) else None)
        # set FileObj attribute "ID Columns", referenced in dim_cols below
        self.id_cols = df.loc[df['Potential ID Column'] == True, 'Column Name'].tolist()
        
        # find the min and max length
        for col in self.df.columns:
            if self.df[col].count() > 0:
                if self.df[col].dtype == 'object':
                    col_values_precision_series = self.df[col].astype('str').str.len()
                    max_precision_value = max(col_values_precision_series)
                    min_precision_value = min(col_values_precision_series)
                elif self.df[col].dtype in ['int', 'int64', 'int32']:
                    max_precision_value = self.df[col].max()
                    min_precision_value = self.df[col].min()
                elif self.df[col].dtype in ['float', 'float64', 'float32']:
                    col_values_precision_series = self.df[col].astype('str')
                    col_values_precision_df = col_values_precision_series.str.split('.', expand=True)
                    # precision
                    min_precision_value = max(col_values_precision_df[0].str.len() + col_values_precision_df[1].str.len())
                    # scale
                    max_precision_value = max(col_values_precision_df[1].str.len())
            else:
                min_precision_value = 0
                max_precision_value = 0
                df.loc[df['Column Name'] == col, 'Data Type'] = 'N/A'
                
            df.loc[df['Column Name'] == col, 'Min Length|Value/Precision'] = min_precision_value
            df.loc[df['Column Name'] == col, 'Max Length|Value/Scale'] = max_precision_value
            # set FileObj attribute "Dim Columns"
            if self.df[col].dtype == 'object' and col not in self.id_cols:
                self.dim_cols.append(col)
        
        return df[['Column Name', 'Clean Column Name', 'Data Type', 'Min Length|Value/Precision', 
            'Max Length|Value/Scale', 'Potential ID Column']]
    
    
    def get_text_distinct_values(self):
        """
        returns: dataframe of column names and series of distinct values
        """
        self.log.info('Retrieving Text Value Distribution')
        results_dict = {}
        pandas_numeric_dtype_list = ['int', 'int64', 'int32', 'float', 'float64', 'float32']
        for col in self.df.columns:
            if self.df[col].dtype in pandas_numeric_dtype_list and col not in self.id_cols:
                results_dict[col] = pd.DataFrame(['NA for numeric columns'], columns=[col])
            else:
                df = pd.DataFrame(self.df[col].value_counts())
                df_null = pd.DataFrame({col: len(self.df[self.df[col].isna()])}, index=['NULL'])
                df = pd.concat([df_null, df], sort=False)
                df.index.name = col
                df.rename(index=str, columns={col: f'{col}_counts'}, inplace=True)
                results_dict[col] = df.reset_index()
        
        return pd.concat(results_dict.values(), axis=1, join='outer', sort=True)
    
    
    def get_numeric_value_distribution(self):
        """
        returns: dataframe of descriptive stats for numeric columns
        """
        self.log.info('Retrieving Numeric Value Distribution')
        df = pd.DataFrame(self.df.describe()).reset_index()
        df.rename(index=str, columns={'index': 'Stat'}, inplace=True)
        return df
    
    
    def get_primary_keys(self):
        """
        analyzes dataframe to see the maximum number of non-metric columns that can be part of a primary key
        this is done by checking for columns that when grouped, retain the same number of distinct records as the
        oringinal dataframe
        returns: dataframe of suggested primary key(s) and dataframe of potential ID fields"""
        self.log.info('Looking for Potential Primary Key(s)')

        pk_1 = []
        pk_2 = []
        df_len = 0
        id_cols = self.id_cols.copy()
        dim_cols = self.dim_cols.copy()
        for col in id_cols + dim_cols:
            new_len = len(self.df.groupby(pk_1 + [col]).count())
            if new_len > df_len:
                df_len = new_len
                pk_1.append(col)
            else:
                pass
            
        id_cols.reverse()
        dim_cols.reverse()
        df_len = 0
        for col in id_cols + dim_cols:
            if len(self.df.groupby(pk_2 + [col]).count()) < df_len:
                pk_2.append(col)
            else:
                pass
            
        return pd.DataFrame({'Column Name': list(set(pk_1 + pk_2))})

def _modify_camel_case_id_names(x):
    results = re.search(r'([a-z]+ID$)', x)
    if results:
        for group in results.groups():
            if group:
                return x.replace(group, group[:-2] + '_ID')
    else:
        return x
