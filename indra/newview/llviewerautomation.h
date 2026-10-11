/** Local developer automation and asynchronous Release CPU/GPU captures. */
#ifndef LL_LLVIEWERAUTOMATION_H
#define LL_LLVIEWERAUTOMATION_H

namespace LLViewerAutomation
{
    void processRequests();
    void applyCamera();
    void beginCPUFrame();
    void endCPUFrame();
    void beginFrame();
    void endFrame();
    void cleanup();

    // Inclusive main-thread wall time; inactive captures and worker threads are ignored.
    class CPUScope
    {
    public:
        explicit CPUScope(const char* name);
        ~CPUScope();
        CPUScope(const CPUScope&) = delete;
        CPUScope& operator=(const CPUScope&) = delete;
    private:
        double* mElapsed = nullptr;
        double mStart = 0;
    };

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
#define LL_AUTOMATION_CPU_SCOPE(name) LLViewerAutomation::CPUScope LL_AUTOMATION_JOIN(automation_cpu_, __LINE__)(name)
#endif
