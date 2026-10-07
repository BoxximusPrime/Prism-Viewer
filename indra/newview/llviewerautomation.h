/** Local developer automation and asynchronous Release GPU captures. */
#ifndef LL_LLVIEWERAUTOMATION_H
#define LL_LLVIEWERAUTOMATION_H

namespace LLViewerAutomation
{
    void processRequests();
    void applyCamera();
    void beginFrame();
    void endFrame();
    void cleanup();

    // Timestamp pairs allow nested scopes without interfering with GL_TIME_ELAPSED.
    // Disabled captures do not issue any GL commands.
    class GPUScope
    {
    public:
        explicit GPUScope(const char* name);
        ~GPUScope();
        GPUScope(const GPUScope&) = delete;
        GPUScope& operator=(const GPUScope&) = delete;
    private:
        unsigned int mEnd = 0;
    };
}
#define LL_AUTOMATION_JOIN_(a,b) a##b
#define LL_AUTOMATION_JOIN(a,b) LL_AUTOMATION_JOIN_(a,b)
#define LL_AUTOMATION_GPU_SCOPE(name) LLViewerAutomation::GPUScope LL_AUTOMATION_JOIN(automation_gpu_, __LINE__)(name)
#endif
