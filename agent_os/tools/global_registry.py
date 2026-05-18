"""Global tool registry with auto-registration of all built-in tools"""

import threading
from agent_os.tools.registry import ToolRegistry

# Thread-safe singleton pattern (Fix #4: Remove Global State Anti-Pattern)
_registry_instance = None
_registry_lock = threading.Lock()


def get_global_registry():
    """
    Get or create global registry with all tools pre-registered.

    Thread-safe singleton implementation that lazy-loads all built-in tools
    on first access.

    Returns:
        ToolRegistry: Singleton registry instance with all tools
    """
    global _registry_instance

    # Double-checked locking for thread safety
    if _registry_instance is None:
        with _registry_lock:
            # Check again after acquiring lock
            if _registry_instance is None:
                _registry_instance = ToolRegistry()

        # Core tools (no optional dependencies)
        tool_classes = []

        # Research tools
        try:
            from agent_os.tools.library.wikipedia import WikipediaSearchTool, WikipediaContentTool
            tool_classes.extend([WikipediaSearchTool, WikipediaContentTool])
        except ImportError:
            pass

        try:
            from agent_os.tools.library.arxiv import ArxivSearchTool, ArxivPaperTool
            tool_classes.extend([ArxivSearchTool, ArxivPaperTool])
        except ImportError:
            pass

        try:
            from agent_os.tools.library.pdf import PDFTextExtractorTool, PDFMetadataTool
            tool_classes.extend([PDFTextExtractorTool, PDFMetadataTool])
        except ImportError:
            pass

        try:
            from agent_os.tools.library.citation import CitationGeneratorTool
            tool_classes.append(CitationGeneratorTool)
        except ImportError:
            pass

        # Web tools (require bs4)
        try:
            from agent_os.tools.library.web import WebScraperTool, HTTPRequestTool
            tool_classes.extend([WebScraperTool, HTTPRequestTool])
        except ImportError:
            pass

        # File tools
        try:
            from agent_os.tools.library.file import FileReaderTool, JSONProcessorTool, CSVProcessorTool, FileWriterTool, FileDeleterTool, DirectoryListTool
            tool_classes.extend([FileReaderTool, JSONProcessorTool, CSVProcessorTool, FileWriterTool, FileDeleterTool, DirectoryListTool])
        except ImportError:
            pass

        # File comparison tools
        try:
            from agent_os.tools.library.file_compare import FileCompareTool, FileStatsTool
            tool_classes.extend([FileCompareTool, FileStatsTool])
        except ImportError:
            pass

        # Security tools
        try:
            from agent_os.tools.library.security import PIIDetectorTool, PIIMaskTool, PIIValidatorTool
            tool_classes.extend([PIIDetectorTool, PIIMaskTool, PIIValidatorTool])
        except ImportError:
            pass

        try:
            from agent_os.tools.library.guardrails import PromptInjectionDetector, ContentModerationTool
            tool_classes.extend([PromptInjectionDetector, ContentModerationTool])
        except ImportError:
            pass

        # Git tools (read operations)
        try:
            from agent_os.tools.library.git import GitCloneTool, GitStatusTool, GitDiffTool, GitLogTool, GitBranchTool
            tool_classes.extend([GitCloneTool, GitStatusTool, GitDiffTool, GitLogTool, GitBranchTool])
        except ImportError:
            pass

        # Git tools (write operations)
        try:
            from agent_os.tools.library.git_write import GitCommitTool, GitPushTool, GitPRTool, GitAddTool
            tool_classes.extend([GitCommitTool, GitPushTool, GitPRTool, GitAddTool])
        except ImportError:
            pass

        # Git initialization and GitHub management tools
        try:
            from agent_os.tools.library.git_init import (
                GitInitTool,
                GitHubRepoTool,
                GitHubSecretsTool,
                GitBranchCreateTool,
                GitHubRepoListTool,
                GitRemoteTool
            )
            tool_classes.extend([
                GitInitTool,
                GitHubRepoTool,
                GitHubSecretsTool,
                GitBranchCreateTool,
                GitHubRepoListTool,
                GitRemoteTool
            ])
        except ImportError:
            pass

        # Code analysis tools
        try:
            from agent_os.tools.library.code_analysis import (
                TechStackAnalyzerTool,
                DependencyScannerTool,
                DockerfileAnalyzerTool,
                DockerfileGeneratorTool,
                RequirementsValidatorTool,
                AppConfigGeneratorTool
            )
            tool_classes.extend([
                TechStackAnalyzerTool,
                DependencyScannerTool,
                DockerfileAnalyzerTool,
                DockerfileGeneratorTool,
                RequirementsValidatorTool,
                AppConfigGeneratorTool
            ])
        except ImportError:
            pass

        # Secrets management tools
        try:
            from agent_os.tools.library.secrets import EnvFileReaderTool, GCPSecretManagerTool, SecretSyncTool
            tool_classes.extend([EnvFileReaderTool, GCPSecretManagerTool, SecretSyncTool])
        except ImportError:
            pass

        # GCP Services tools (deployment)
        try:
            from agent_os.tools.library.gcp_services import GCPServiceEnablerTool, GCPCloudRunTool, GCPCloudBuildTool
            tool_classes.extend([GCPServiceEnablerTool, GCPCloudRunTool, GCPCloudBuildTool])
        except ImportError:
            pass

        # GCP Logging tools
        try:
            from agent_os.tools.library.gcp_logging import GCPLoggingTool, GCPErrorAnalyzerTool, CloudRunLogTool
            tool_classes.extend([GCPLoggingTool, GCPErrorAnalyzerTool, CloudRunLogTool])
        except ImportError:
            pass

        # Shell tools
        try:
            from agent_os.tools.library.shell import SafeShellExecutorTool
            tool_classes.append(SafeShellExecutorTool)
        except ImportError:
            pass

        # Database tools (SQL with schema discovery)
        try:
            from agent_os.tools.library.database import SQLExecutorTool, DatabaseListTablesTool, DatabaseDescribeTableTool
            tool_classes.extend([SQLExecutorTool, DatabaseListTablesTool, DatabaseDescribeTableTool])
        except ImportError:
            pass

        # DataFrame tools (require pandas, optional: polars, duckdb)
        try:
            from agent_os.tools.library.dataframe_tools import (
                DataFrameReadExcelTool,
                DataFrameReadParquetTool,
                DataFrameWriteExcelTool,
                DataFrameWriteParquetTool,
                DataFrameDescribeTool,
                DataFrameFilterRowsTool,
                DataFrameDropDuplicatesTool,
                DataFrameHandleMissingTool,
                DataFrameSortTool,
                DataFrameAddColumnTool,
                DataFrameGroupAggregateTool,
                DataFrameMergeTool,
                DataFrameConvertTypesTool,
                DataFrameCleanOutliersTool,
                DataFrameCorrelationTool,
                DataFrameValidateSchemaTool,
                DataFrameQualityReportTool,
                DataFrameVisualizeTool,
                DataFrameFetchAPITool,
                DataFramePivotTool,
                DataFrameAnalyzeFolderTool
            )
            tool_classes.extend([
                DataFrameReadExcelTool,
                DataFrameReadParquetTool,
                DataFrameWriteExcelTool,
                DataFrameWriteParquetTool,
                DataFrameDescribeTool,
                DataFrameFilterRowsTool,
                DataFrameDropDuplicatesTool,
                DataFrameHandleMissingTool,
                DataFrameSortTool,
                DataFrameAddColumnTool,
                DataFrameGroupAggregateTool,
                DataFrameMergeTool,
                DataFrameConvertTypesTool,
                DataFrameCleanOutliersTool,
                DataFrameCorrelationTool,
                DataFrameValidateSchemaTool,
                DataFrameQualityReportTool,
                DataFrameVisualizeTool,
                DataFrameFetchAPITool,
                DataFramePivotTool,
                DataFrameAnalyzeFolderTool
            ])
        except ImportError:
            pass

        # Data export/import tools (CSV↔SQLite, format conversion)
        try:
            from agent_os.tools.library.data_export import (
                CSVToSQLiteTool,
                DataFormatConverterTool,
                SQLiteToCSVTool
            )
            tool_classes.extend([
                CSVToSQLiteTool,
                DataFormatConverterTool,
                SQLiteToCSVTool
            ])
        except ImportError:
            pass

        # Email tools
        try:
            from agent_os.tools.library.email import EmailTemplateManager
            tool_classes.append(EmailTemplateManager)
        except ImportError:
            pass

        # Workflow tracking tools
        try:
            from agent_os.tools.library.workflow_tracking import (
                ProgressLoggerTool, ExecutionTimerTool, PhaseMonitorTool,
                ConsoleFormatterTool, StatusReporterTool
            )
            tool_classes.extend([
                ProgressLoggerTool, ExecutionTimerTool, PhaseMonitorTool,
                ConsoleFormatterTool, StatusReporterTool
            ])
        except ImportError:
            pass

        # CI/CD Pipeline tools
        try:
            from agent_os.tools.library.cicd import (
                CloudBuildTriggerTool,
                GitHubActionsGeneratorTool,
                TestRunnerTool,
                CloudBuildConfigGeneratorTool
            )
            tool_classes.extend([
                CloudBuildTriggerTool,
                GitHubActionsGeneratorTool,
                TestRunnerTool,
                CloudBuildConfigGeneratorTool
            ])
        except ImportError:
            pass

        # Enterprise Security tools (container scanner, IAM, secrets scanner)
        try:
            from agent_os.tools.library.security import (
                ContainerScannerTool,
                IAMValidatorTool,
                SecretScannerTool
            )
            tool_classes.extend([
                ContainerScannerTool,
                IAMValidatorTool,
                SecretScannerTool
            ])
        except ImportError:
            pass

        # Scalability tools
        try:
            from agent_os.tools.library.scalability import (
                AutoScalingConfigTool,
                TrafficSplittingTool,
                RollbackTool,
                LoadBalancerConfigTool,
                HealthCheckConfigTool
            )
            tool_classes.extend([
                AutoScalingConfigTool,
                TrafficSplittingTool,
                RollbackTool,
                LoadBalancerConfigTool,
                HealthCheckConfigTool
            ])
        except ImportError:
            pass

        # Infrastructure tools
        try:
            from agent_os.tools.library.infrastructure import (
                TerraformGeneratorTool,
                VPCConfigTool,
                CloudSQLProvisioningTool
            )
            tool_classes.extend([
                TerraformGeneratorTool,
                VPCConfigTool,
                CloudSQLProvisioningTool
            ])
        except ImportError:
            pass

        # Deployment Introspection tools
        try:
            from agent_os.tools.library.introspection import (
                CloudRunServiceDiscoveryTool,
                CloudRunConfigReaderTool,
                RevisionInspectorTool,
                HealthMonitorTool,
                ResourceMetricsTool
            )
            tool_classes.extend([
                CloudRunServiceDiscoveryTool,
                CloudRunConfigReaderTool,
                RevisionInspectorTool,
                HealthMonitorTool,
                ResourceMetricsTool
            ])
        except ImportError:
            pass

        # Environment-Aware Deployment tools
        try:
            from agent_os.tools.library.environment import (
                EnvironmentDetectorTool,
                ServiceSelectorTool,
                CostOptimizerTool,
                SecurityLayerTool
            )
            tool_classes.extend([
                EnvironmentDetectorTool,
                ServiceSelectorTool,
                CostOptimizerTool,
                SecurityLayerTool
            ])
        except ImportError:
            pass

        # GCP Infrastructure tools (PHASE 0 - One-time Platform Setup)
        try:
            from agent_os.tools.library.gcp_infrastructure import (
                GCPProjectTool,
                ArtifactRegistryTool,
                ServiceAccountTool,
                IAMRoleAssignerTool,
                WorkloadIdentityTool,
                MultiEnvSetupTool,
                BranchTriggerTool
            )
            tool_classes.extend([
                GCPProjectTool,
                ArtifactRegistryTool,
                ServiceAccountTool,
                IAMRoleAssignerTool,
                WorkloadIdentityTool,
                MultiEnvSetupTool,
                BranchTriggerTool
            ])
        except ImportError:
            pass

        # UNIVERSAL GCP TOOLS (replaces 50+ specific tools)
        try:
            from agent_os.tools.library.gcp_cli import GCPCLITool, GCPAPIClientTool, TerraformExecutorTool
            tool_classes.extend([GCPCLITool, GCPAPIClientTool, TerraformExecutorTool])
        except ImportError:
            pass

        # Multi-service orchestration tools
        try:
            from agent_os.tools.library.gcp_orchestration import ServiceOrchestrationTool, InfraProvisionerTool
            tool_classes.extend([ServiceOrchestrationTool, InfraProvisionerTool])
        except ImportError:
            pass

        # Geospatial tools (require geopandas, shapely, rtree)
        try:
            from agent_os.tools.library.geo_spatial import (
                GeoLoadPointsTool, GeoBuildRTreeTool, GeoBBoxQueryTool,
                GeoRadiusQueryTool, GeoSpatialStatsTool, GeoExportTool
            )
            tool_classes.extend([
                GeoLoadPointsTool, GeoBuildRTreeTool, GeoBBoxQueryTool,
                GeoRadiusQueryTool, GeoSpatialStatsTool, GeoExportTool
            ])
        except ImportError:
            pass

        # GWDB Ingest tools
        try:
            from agent_os.tools.library.gwdb_ingest import (
                GWDBLoadFileTool, GWDBLoadWellMainTool, GWDBLoadSQLTablesTool,
                GWDBPreviewTool, GWDBListLoadedTool
            )
            tool_classes.extend([
                GWDBLoadFileTool, GWDBLoadWellMainTool, GWDBLoadSQLTablesTool,
                GWDBPreviewTool, GWDBListLoadedTool
            ])
        except ImportError:
            pass

        # GWDB Query tools
        try:
            from agent_os.tools.library.gwdb_query import (
                GWDBFilterTool, GWDBCountTool, GWDBAggregateTool,
                GWDBSearchTool, GWDBDescribeColumnTool, GWDBSQLQueryTool
            )
            tool_classes.extend([
                GWDBFilterTool, GWDBCountTool, GWDBAggregateTool,
                GWDBSearchTool, GWDBDescribeColumnTool, GWDBSQLQueryTool
            ])
        except ImportError:
            pass

        # GWDB Analyze tools
        try:
            from agent_os.tools.library.gwdb_analyze import (
                GWDBMissingValuesTool, GWDBDuplicatesTool, GWDBDtypeCheckTool,
                GWDBOutliersTool, GWDBValueDistributionTool, GWDBDataProfileTool,
                GWDBCompareSchemasTool
            )
            tool_classes.extend([
                GWDBMissingValuesTool, GWDBDuplicatesTool, GWDBDtypeCheckTool,
                GWDBOutliersTool, GWDBValueDistributionTool, GWDBDataProfileTool,
                GWDBCompareSchemasTool
            ])
        except ImportError:
            pass

        # GWDB Clean tools (data modification)
        try:
            from agent_os.tools.library.gwdb_clean import (
                GWDBRemoveDuplicatesTool, GWDBFillMissingTool,
                GWDBDropColumnsTool, GWDBRenameColumnsTool
            )
            tool_classes.extend([
                GWDBRemoveDuplicatesTool, GWDBFillMissingTool,
                GWDBDropColumnsTool, GWDBRenameColumnsTool
            ])
        except ImportError:
            pass

        # GWDB Transform tools (create derived tables via SQL)
        try:
            from agent_os.tools.library.gwdb_transform import GWDBCreateTableTool
            tool_classes.append(GWDBCreateTableTool)
        except ImportError:
            pass

        # GWDB Merge tools (union, align)
        try:
            from agent_os.tools.library.gwdb_merge import GWDBUnionTablesTool, GWDBAlignColumnsTool
            tool_classes.extend([GWDBUnionTablesTool, GWDBAlignColumnsTool])
        except ImportError:
            pass

        # GWDB Export tools
        try:
            from agent_os.tools.library.gwdb_export import (
                GWDBToJSONTool, GWDBToCSVTool, GWDBToExcelTool,
                GWDBToParquetTool, GWDBToSQLiteTool, GWDBSaveAsTool
            )
            tool_classes.extend([
                GWDBToJSONTool, GWDBToCSVTool, GWDBToExcelTool,
                GWDBToParquetTool, GWDBToSQLiteTool, GWDBSaveAsTool
            ])
        except ImportError:
            pass

        # GWDB Schema tools
        try:
            from agent_os.tools.library.gwdb_schema import (
                GWDBShowSchemaTool, GWDBTableInfoTool,
                GWDBLookupValuesTool, GWDBValidateFKTool
            )
            tool_classes.extend([
                GWDBShowSchemaTool, GWDBTableInfoTool,
                GWDBLookupValuesTool, GWDBValidateFKTool
            ])
        except ImportError:
            pass

        # GWDB Push tools (HITL-enforced)
        try:
            from agent_os.tools.library.gwdb_push import (
                GWDBMapToTablesTool, GWDBPreviewPushTool, GWDBRequestApprovalTool,
                GWDBExecutePushTool, GWDBVerifyPushTool, GWDBPushStatusTool
            )
            tool_classes.extend([
                GWDBMapToTablesTool, GWDBPreviewPushTool, GWDBRequestApprovalTool,
                GWDBExecutePushTool, GWDBVerifyPushTool, GWDBPushStatusTool
            ])
        except ImportError:
            pass

        # Register all successfully imported tools
        for tool_class in tool_classes:
            try:
                _registry_instance.register(tool_class())
            except Exception:
                pass

    return _registry_instance


def reset_global_registry():
    """
    Reset the global registry (for testing and cleanup).

    Clears all tools and forces re-initialization on next get_global_registry() call.
    Use this in test teardown to ensure test isolation.
    """
    global _registry_instance

    with _registry_lock:
        if _registry_instance is not None:
            _registry_instance.clear(clear_stats=True)
            _registry_instance = None


def is_registry_initialized():
    """
    Check if global registry has been initialized.

    Returns:
        bool: True if registry exists, False otherwise
    """
    return _registry_instance is not None
