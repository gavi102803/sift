from pydantic import Field

from sift_backend.schemas.base import SiftBaseModel


class AppStatusResponse(SiftBaseModel):
    env: str
    model_provider: str = Field(alias="modelProvider")
    explain_model: str = Field(alias="explainModel")
    web_search_enabled: bool = Field(alias="webSearchEnabled")
    database_url: str = Field(alias="databaseURL")
    provider_base_url: str | None = Field(default=None, alias="providerBaseURL")
    api_key_configured: bool = Field(default=False, alias="apiKeyConfigured")
    api_key_preview: str | None = Field(default=None, alias="apiKeyPreview")


class ModelDiagnosticResponse(SiftBaseModel):
    ok: bool
    provider: str
    model: str
    message: str
    web_search_used: bool | None = Field(default=None, alias="webSearchUsed")
    citation_count: int | None = Field(default=None, ge=0, alias="citationCount")


class ProviderModelDTO(SiftBaseModel):
    id: str
    owned_by: str = Field(alias="ownedBy")


class ModelProviderSettingsResponse(SiftBaseModel):
    provider_type: str = Field(alias="providerType")
    base_url: str = Field(alias="baseURL")
    api_key_configured: bool = Field(alias="apiKeyConfigured")
    api_key_preview: str | None = Field(default=None, alias="apiKeyPreview")
    explain_model: str = Field(alias="explainModel")
    web_search_enabled: bool = Field(alias="webSearchEnabled")
    supports_web_search: bool = Field(alias="supportsWebSearch")


class UpdateModelProviderSettingsRequest(SiftBaseModel):
    provider_type: str = Field(alias="providerType")
    base_url: str = Field(alias="baseURL")
    api_key: str | None = Field(default=None, alias="apiKey")
    explain_model: str = Field(alias="explainModel")
    web_search_enabled: bool = Field(default=True, alias="webSearchEnabled")


class WebProviderSettingsResponse(SiftBaseModel):
    provider_type: str = Field(alias="providerType")
    api_key_configured: bool = Field(alias="apiKeyConfigured")
    api_key_preview: str | None = Field(default=None, alias="apiKeyPreview")
    web_search_enabled: bool = Field(alias="webSearchEnabled")


class UpdateWebProviderSettingsRequest(SiftBaseModel):
    provider_type: str = Field(alias="providerType")
    api_key: str | None = Field(default=None, alias="apiKey")
    web_search_enabled: bool = Field(default=True, alias="webSearchEnabled")


class ProviderModelListResponse(SiftBaseModel):
    models: list[ProviderModelDTO]


class RuntimeProviderOptionDTO(SiftBaseModel):
    id: str
    name: str
    description: str
    adapter: str
    default_base_url: str = Field(alias="defaultBaseURL")
    default_model: str = Field(alias="defaultModel")
    requires_api_key: bool = Field(alias="requiresApiKey")
    supports_model_listing: bool = Field(alias="supportsModelListing")
    status: str
    is_advanced: bool = Field(default=False, alias="isAdvanced")
    configured_base_url: str | None = Field(default=None, alias="configuredBaseURL")
    configured_model: str | None = Field(default=None, alias="configuredModel")
    api_key_configured: bool = Field(default=False, alias="apiKeyConfigured")
    api_key_preview: str | None = Field(default=None, alias="apiKeyPreview")


class RuntimeProviderCatalogResponse(SiftBaseModel):
    providers: list[RuntimeProviderOptionDTO]


class WebProviderOptionDTO(SiftBaseModel):
    id: str
    name: str
    description: str
    requires_api_key: bool = Field(alias="requiresApiKey")
    supports_search: bool = Field(alias="supportsSearch")
    supports_extract: bool = Field(alias="supportsExtract")
    status: str
    is_default: bool = Field(default=False, alias="isDefault")
    api_key_configured: bool = Field(default=False, alias="apiKeyConfigured")
    api_key_preview: str | None = Field(default=None, alias="apiKeyPreview")


class WebProviderCatalogResponse(SiftBaseModel):
    providers: list[WebProviderOptionDTO]
