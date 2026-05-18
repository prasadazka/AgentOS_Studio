"""Pre-built production-ready tools - lazy imports to handle optional dependencies"""

# This module now provides lazy imports to avoid failures when optional dependencies are missing
# Tools are registered in agent_os/tools/global_registry.py which handles ImportErrors gracefully

__all__ = []

# Research tools
try:
    from agent_os.tools.library.wikipedia import WikipediaSearchTool, WikipediaContentTool
    __all__.extend(["WikipediaSearchTool", "WikipediaContentTool"])
except ImportError:
    pass

try:
    from agent_os.tools.library.arxiv import ArxivSearchTool, ArxivPaperTool
    __all__.extend(["ArxivSearchTool", "ArxivPaperTool"])
except ImportError:
    pass

try:
    from agent_os.tools.library.pdf import PDFTextExtractorTool, PDFMetadataTool
    __all__.extend(["PDFTextExtractorTool", "PDFMetadataTool"])
except ImportError:
    pass

try:
    from agent_os.tools.library.citation import CitationGeneratorTool
    __all__.append("CitationGeneratorTool")
except ImportError:
    pass

# Web tools (require bs4)
try:
    from agent_os.tools.library.web import WebScraperTool, HTTPRequestTool
    __all__.extend(["WebScraperTool", "HTTPRequestTool"])
except ImportError:
    pass

# Search tools (optional dependencies)
try:
    from agent_os.tools.library.search import TavilySearchTool, DuckDuckGoSearchTool, WebSearchTool
    __all__.extend(["TavilySearchTool", "DuckDuckGoSearchTool", "WebSearchTool"])
except ImportError:
    pass

# File tools (no external dependencies)
try:
    from agent_os.tools.library.file import FileReaderTool, JSONProcessorTool, CSVProcessorTool, FileWriterTool, FileDeleterTool, DirectoryListTool
    __all__.extend(["FileReaderTool", "JSONProcessorTool", "CSVProcessorTool", "FileWriterTool", "FileDeleterTool", "DirectoryListTool"])
except ImportError:
    pass

# File comparison tools (no external dependencies)
try:
    from agent_os.tools.library.file_compare import FileCompareTool, FileStatsTool
    __all__.extend(["FileCompareTool", "FileStatsTool"])
except ImportError:
    pass

# Database tools
try:
    from agent_os.tools.library.database import SQLExecutorTool
    __all__.append("SQLExecutorTool")
except ImportError:
    pass

# Security tools
try:
    from agent_os.tools.library.security import PIIDetectorTool, PIIMaskTool, PIIValidatorTool
    __all__.extend(["PIIDetectorTool", "PIIMaskTool", "PIIValidatorTool"])
except ImportError:
    pass

# Vector tools
try:
    from agent_os.tools.library.vector import VectorStoreTool, VectorSearchTool, VectorDeleteTool
    __all__.extend(["VectorStoreTool", "VectorSearchTool", "VectorDeleteTool"])
except ImportError:
    pass

# Text tools
try:
    from agent_os.tools.library.text import TextSummarizerTool, RegexProcessorTool, StringFormatterTool, PromptBuilderTool
    __all__.extend(["TextSummarizerTool", "RegexProcessorTool", "StringFormatterTool", "PromptBuilderTool"])
except ImportError:
    pass

# Language tools
try:
    from agent_os.tools.library.language import LanguageDetectorTool, TranslationTool, MultilingualTextTool
    __all__.extend(["LanguageDetectorTool", "TranslationTool", "MultilingualTextTool"])
except ImportError:
    pass

# Guardrails
try:
    from agent_os.tools.library.guardrails import PromptInjectionDetector, ContentModerationTool, GuardrailsEngine
    __all__.extend(["PromptInjectionDetector", "ContentModerationTool", "GuardrailsEngine"])
except ImportError:
    pass

# Git tools (read operations)
try:
    from agent_os.tools.library.git import GitCloneTool, GitStatusTool, GitDiffTool, GitLogTool, GitBranchTool
    __all__.extend(["GitCloneTool", "GitStatusTool", "GitDiffTool", "GitLogTool", "GitBranchTool"])
except ImportError:
    pass

# Git tools (write operations)
try:
    from agent_os.tools.library.git_write import GitCommitTool, GitPushTool, GitAddTool, GitPRTool
    __all__.extend(["GitCommitTool", "GitPushTool", "GitAddTool", "GitPRTool"])
except ImportError:
    pass

# CI/CD tools
try:
    from agent_os.tools.library.cicd import CloudBuildTriggerTool
    __all__.append("CloudBuildTriggerTool")
except ImportError:
    pass

# Secret management tools
try:
    from agent_os.tools.library.secrets import EnvFileReaderTool
    __all__.append("EnvFileReaderTool")
except ImportError:
    pass

# Shell tools
try:
    from agent_os.tools.library.shell import ShellExecutorTool, SafeShellExecutorTool, UnsafeShellExecutorTool, ApprovalShellExecutorTool
    __all__.extend(["ShellExecutorTool", "SafeShellExecutorTool", "UnsafeShellExecutorTool", "ApprovalShellExecutorTool"])
except ImportError:
    pass

# GCP tools (require google-cloud libraries)
try:
    from agent_os.tools.library.gcp import GCPStorageTool, GCPBigQueryTool, GCPComputeTool, GCPIAMTool
    __all__.extend(["GCPStorageTool", "GCPBigQueryTool", "GCPComputeTool", "GCPIAMTool"])
except ImportError:
    pass

# Cost guardrails
try:
    from agent_os.tools.library.cost_guardrails import (
        CostEstimatorTool, BudgetManager, CostAwareApprovalManager,
        Budget, BudgetPeriod, CostEstimate, SpendRecord, GCPPricing
    )
    __all__.extend(["CostEstimatorTool", "BudgetManager", "CostAwareApprovalManager",
                    "Budget", "BudgetPeriod", "CostEstimate", "SpendRecord", "GCPPricing"])
except ImportError:
    pass

# Email tools (require email-validator package)
try:
    from agent_os.tools.library.email import EmailSenderTool, EmailTemplateManager
    __all__.extend(["EmailSenderTool", "EmailTemplateManager"])
except ImportError:
    pass

# Workflow tracking tools
try:
    from agent_os.tools.library.workflow_tracking import (
        ProgressLoggerTool, ExecutionTimerTool, PhaseMonitorTool,
        ConsoleFormatterTool, StatusReporterTool
    )
    __all__.extend(["ProgressLoggerTool", "ExecutionTimerTool", "PhaseMonitorTool",
                    "ConsoleFormatterTool", "StatusReporterTool"])
except ImportError:
    pass

# Config-driven GCP tools (YAML-based, replaces hardcoded tools)
try:
    from agent_os.tools.library.config_tools import (
        ConfigDrivenTool, CloudSQLTool, PubSubTool, CloudStorageTool,
        CloudRunTool, CloudBuildTool, ArtifactRegistryTool,
        ServiceAccountTool, WorkloadIdentityTool, register_config_tools
    )
    __all__.extend([
        "ConfigDrivenTool", "CloudSQLTool", "PubSubTool", "CloudStorageTool",
        "CloudRunTool", "CloudBuildTool", "ArtifactRegistryTool",
        "ServiceAccountTool", "WorkloadIdentityTool", "register_config_tools"
    ])
except ImportError:
    pass

# GCP Services - API enablement (non-config, unique functionality)
try:
    from agent_os.tools.library.gcp_services import GCPServiceEnablerTool
    __all__.append("GCPServiceEnablerTool")
except ImportError:
    pass

# GCP Infrastructure tools (non-config, orchestration tools)
try:
    from agent_os.tools.library.gcp_infrastructure import (
        GCPProjectTool, IAMRoleAssignerTool, MultiEnvSetupTool, BranchTriggerTool
    )
    __all__.extend(["GCPProjectTool", "IAMRoleAssignerTool", "MultiEnvSetupTool", "BranchTriggerTool"])
except ImportError:
    pass

# Geospatial tools (require geopandas, shapely, rtree)
try:
    from agent_os.tools.library.geo_spatial import (
        GeoLoadPointsTool, GeoBuildRTreeTool, GeoBBoxQueryTool,
        GeoRadiusQueryTool, GeoSpatialStatsTool, GeoExportTool
    )
    __all__.extend([
        "GeoLoadPointsTool", "GeoBuildRTreeTool", "GeoBBoxQueryTool",
        "GeoRadiusQueryTool", "GeoSpatialStatsTool", "GeoExportTool"
    ])
except ImportError:
    pass

# GWDB Ingest tools (load pipe-delimited TXT files)
try:
    from agent_os.tools.library.gwdb_ingest import (
        GWDBLoadFileTool, GWDBLoadWellMainTool, GWDBLoadSQLTablesTool,
        GWDBPreviewTool, GWDBListLoadedTool
    )
    __all__.extend([
        "GWDBLoadFileTool", "GWDBLoadWellMainTool", "GWDBLoadSQLTablesTool",
        "GWDBPreviewTool", "GWDBListLoadedTool"
    ])
except ImportError:
    pass

# GWDB Query tools (filter, count, aggregate, search, SQL)
try:
    from agent_os.tools.library.gwdb_query import (
        GWDBFilterTool, GWDBCountTool, GWDBAggregateTool,
        GWDBSearchTool, GWDBDescribeColumnTool, GWDBSQLQueryTool
    )
    __all__.extend([
        "GWDBFilterTool", "GWDBCountTool", "GWDBAggregateTool",
        "GWDBSearchTool", "GWDBDescribeColumnTool", "GWDBSQLQueryTool"
    ])
except ImportError:
    pass

# GWDB Analyze tools (data quality, profiling)
try:
    from agent_os.tools.library.gwdb_analyze import (
        GWDBMissingValuesTool, GWDBDuplicatesTool, GWDBDtypeCheckTool,
        GWDBOutliersTool, GWDBValueDistributionTool, GWDBDataProfileTool,
        GWDBCompareSchemasTool
    )
    __all__.extend([
        "GWDBMissingValuesTool", "GWDBDuplicatesTool", "GWDBDtypeCheckTool",
        "GWDBOutliersTool", "GWDBValueDistributionTool", "GWDBDataProfileTool",
        "GWDBCompareSchemasTool"
    ])
except ImportError:
    pass

# GWDB Transform tools (create derived tables via SQL)
try:
    from agent_os.tools.library.gwdb_transform import GWDBCreateTableTool
    __all__.append("GWDBCreateTableTool")
except ImportError:
    pass

# GWDB Merge tools (union tables, align schemas)
try:
    from agent_os.tools.library.gwdb_merge import GWDBUnionTablesTool, GWDBAlignColumnsTool
    __all__.extend(["GWDBUnionTablesTool", "GWDBAlignColumnsTool"])
except ImportError:
    pass

# GWDB Export tools (JSON, CSV, Excel, Parquet, SQLite)
try:
    from agent_os.tools.library.gwdb_export import (
        GWDBToJSONTool, GWDBToCSVTool, GWDBToExcelTool,
        GWDBToParquetTool, GWDBToSQLiteTool, GWDBSaveAsTool
    )
    __all__.extend([
        "GWDBToJSONTool", "GWDBToCSVTool", "GWDBToExcelTool",
        "GWDBToParquetTool", "GWDBToSQLiteTool", "GWDBSaveAsTool"
    ])
except ImportError:
    pass

# GWDB Schema tools (ER diagram, table info, lookups, FK validation)
try:
    from agent_os.tools.library.gwdb_schema import (
        GWDBShowSchemaTool, GWDBTableInfoTool,
        GWDBLookupValuesTool, GWDBValidateFKTool
    )
    __all__.extend([
        "GWDBShowSchemaTool", "GWDBTableInfoTool",
        "GWDBLookupValuesTool", "GWDBValidateFKTool"
    ])
except ImportError:
    pass

# GWDB Push tools (HITL-enforced data push to SQL tables)
try:
    from agent_os.tools.library.gwdb_push import (
        GWDBMapToTablesTool, GWDBPreviewPushTool, GWDBRequestApprovalTool,
        GWDBExecutePushTool, GWDBVerifyPushTool, GWDBPushStatusTool
    )
    __all__.extend([
        "GWDBMapToTablesTool", "GWDBPreviewPushTool", "GWDBRequestApprovalTool",
        "GWDBExecutePushTool", "GWDBVerifyPushTool", "GWDBPushStatusTool"
    ])
except ImportError:
    pass
